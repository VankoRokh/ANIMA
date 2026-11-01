"""The smoke runner is opt-in; these tests use no model, server or network."""

import json
import subprocess
import urllib.error

import pytest

from anima.cognition.fast_llm import FastLLMTransportError, LlamaCppFastTransport
from scripts import run_stage5_smoke as smoke


def fake_native(self, endpoint, payload, *, timeout_seconds):
    if endpoint.endswith("/apply-template"):
        return {"prompt": json.dumps(payload["messages"])}
    view = json.loads(json.loads(payload["prompt"])[1]["content"].split("TASK_VIEW:\n", 1)[1])
    answer = "CONTINUE" if view["operation"] == "CHOOSE_ACTION" else smoke.MARKER
    return {"content": answer, "tokens_evaluated": 20, "tokens_predicted": 3, "stop": True}


def factory(failure):
    return smoke.ObservedTransport(controlled_failure=failure, **smoke.PARAMETERS)


def test_smoke_cases_use_production_pipeline_and_capture_separate_counters(monkeypatch):
    monkeypatch.setattr(LlamaCppFastTransport, "_post_json", fake_native)
    result = smoke.run_smoke(factory)
    assert result["passed"], [(row["case"], row["validation"]) for row in result["cases"]]
    assert result["temporary_instance_removed"] and result["instance_data_unchanged"]
    assert result["provenance_preserved"] and result["model_has_no_seed_chat_history"]
    cases = {row["case"]: row for row in result["cases"]}
    assert len(cases) == 7
    for name in ("arithmetic", "missing_fact", "infeasible_action"):
        assert cases[name]["counts"]["backend_attempts"] == 0
        assert cases[name]["counts"]["generation_requests"] == 0
        assert cases[name]["http_calls"] == []
    assert cases["arithmetic"]["final_result"] == "0.000001"
    for name in ("cognitive", "action_selection", "invalid_candidate"):
        row = cases[name]
        assert row["counts"] == {"backend_attempts": 1, "backend_completions": 1,
                                 "generation_requests": 1, "generation_responses": 1}
        assert row["validation"]["native_prompt_delivered"]
        assert row["validation"]["projection_reached_transport"]
        assert row["raw_model_response"] is not None
    assert cases["cognitive"]["final_result"] == smoke.MARKER
    assert cases["cognitive"]["context_bundle"]["budget"] == {"max_items": 6, "max_chars": 1200}
    assert not cases["cognitive"]["context_bundle"]["events"]
    invalid = cases["invalid_candidate"]
    assert invalid["raw_model_response"] == "CONTINUE"
    assert invalid["backend_response"] == "SHUTDOWN"
    assert invalid["validation_error"] == "invalid_output_candidate"
    assert invalid["fault_injection"] == "replace_result_after_real_completion"
    failed = cases["transport_failure"]
    assert failed["counts"]["backend_attempts"] == 1
    assert failed["counts"]["backend_completions"] == failed["counts"]["generation_requests"] == 0
    assert failed["backend_audits"][0]["terminal_failure"]
    assert failed["backend_audits"][0]["failure_classification"] == "TRANSPORT"
    assert failed["exception"]["same_controlled_exception"]
    # Evidence must be serializable without losing exact decimal results.
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("answer", ["RESULT=CONTINUE", "CONTINUE."])
def test_smoke_does_not_repair_invalid_real_candidate_or_retry(monkeypatch, answer):
    def invalid_native(self, endpoint, payload, **kwargs):
        response = fake_native(self, endpoint, payload, **kwargs)
        if endpoint.endswith("/completion") and response.get("content") == "CONTINUE":
            response["content"] = answer
        return response
    monkeypatch.setattr(LlamaCppFastTransport, "_post_json", invalid_native)
    result = smoke.run_smoke(factory)
    assert not result["passed"]
    action = next(row for row in result["cases"] if row["case"] == "action_selection")
    assert action["raw_model_response"] == answer
    assert action["validation_error"] == "invalid_output_candidate"
    assert action["final_result"] is None
    assert action["counts"]["backend_attempts"] == action["counts"]["generation_requests"] == 1


def test_unexpected_transport_failure_is_retained_as_failed_smoke_evidence(monkeypatch):
    def unavailable(self, endpoint, payload, **kwargs):
        raise FastLLMTransportError("unavailable")
    monkeypatch.setattr(LlamaCppFastTransport, "_post_json", unavailable)
    result = smoke.run_smoke(factory)
    assert not result["passed"]
    assert len(result["cases"]) == 7
    assert result["temporary_instance_removed"]
    for row in result["cases"]:
        if row["case"] in ("cognitive", "action_selection", "invalid_candidate"):
            assert row["counts"]["backend_attempts"] == 1
            assert row["counts"]["backend_completions"] == row["counts"]["generation_requests"] == 0
            assert row["exception"]["type"] == "FastLLMTransportError"
            assert row["backend_audits"][0]["terminal_failure"]


def metadata(url):
    return {"data": [{"id": smoke.MODEL}]} if url.endswith("/v1/models") else {"build_info": "fake"}


def test_existing_server_is_never_started_or_stopped_by_smoke(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "_ready", lambda url: True)
    monkeypatch.setattr(smoke, "_get_json", metadata)
    def forbidden(*args, **kwargs): raise AssertionError("Must not start another server")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    with smoke.local_server("http://127.0.0.1:8080", "unused", "unused", tmp_path/"server.log") as info:
        assert not info["started_by_smoke"]
    assert not info["owned_process_stopped"]


@pytest.mark.parametrize("body_fails", [False, True])
def test_only_owned_process_is_terminated_even_on_failure(monkeypatch, tmp_path, body_fails):
    class Process:
        pid = 123
        returncode = None
        terminated = 0
        def poll(self): return self.returncode
        def terminate(self): self.terminated += 1; self.returncode = 0
        def wait(self, **kwargs): return self.returncode
    process = Process()
    probes = iter([urllib.error.URLError(ConnectionRefusedError()), True])
    def ready(url):
        answer = next(probes)
        if isinstance(answer, Exception): raise answer
        return answer
    monkeypatch.setattr(smoke, "_ready", ready)
    monkeypatch.setattr(smoke, "_get_json", metadata)
    monkeypatch.setattr(smoke.time, "sleep", lambda duration: None)
    commands = []
    def spawn(command, **kwargs): commands.append(command); return process
    monkeypatch.setattr(subprocess, "Popen", spawn)
    try:
        with smoke.local_server("http://127.0.0.1:8080", "server", "model.gguf", tmp_path/"server.log") as info:
            assert info["pid"] == 123
            if body_fails: raise RuntimeError("controlled body failure")
    except RuntimeError as error:
        assert body_fails and str(error) == "controlled body failure"
    assert process.terminated == 1
    assert info["owned_process_stopped"]
    assert "--no-cache-prompt" in commands[0]
    assert commands[0][commands[0].index("--alias")+1] == smoke.MODEL


def test_wrong_server_model_is_rejected_without_terminating_it(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "_ready", lambda url: True)
    monkeypatch.setattr(smoke, "_get_json", lambda url: {"data": [{"id": "wrong-model"}]})
    with pytest.raises(RuntimeError, match="does not advertise"):
        with smoke.local_server("http://127.0.0.1:8080", "unused", "unused", tmp_path/"server.log"):
            raise AssertionError("Wrong server must not be used")


@pytest.mark.parametrize("answer", ["text", "candidate", "output_contract", "unrelated content"])
def test_wrong_task_content_is_a_failure_not_repaired_or_relabelled(monkeypatch, answer):
    def wrong_literal(self, endpoint, payload, **kwargs):
        response = fake_native(self, endpoint, payload, **kwargs)
        if response.get("content") == smoke.MARKER:
            response["content"] = answer
        return response
    monkeypatch.setattr(LlamaCppFastTransport, "_post_json", wrong_literal)
    result = smoke.run_smoke(factory)
    cognitive = next(row for row in result["cases"] if row["case"] == "cognitive")
    assert not result["passed"] and not cognitive["passed"]
    assert cognitive["raw_model_response"] == cognitive["final_result"] == answer
    assert cognitive["counts"]["generation_requests"] == 1
    assert result["cognitive_check"] == "semantic_projected_delivery_not_independent_memory_recall"


def test_cli_writes_evidence_only_with_injected_transport_and_server(monkeypatch, tmp_path):
    from contextlib import contextmanager
    monkeypatch.setattr(LlamaCppFastTransport, "_post_json", fake_native)
    @contextmanager
    def server(*args, **kwargs):
        info = {"started_by_smoke": True, "owned_process_stopped": False, "models": metadata("/v1/models")}
        try:
            yield info
        finally:
            info["owned_process_stopped"] = True
    monkeypatch.setattr(smoke, "local_server", server)
    monkeypatch.setattr(smoke, "_sha256", lambda path: "fixture-sha256")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "version", "build"))
    output = tmp_path / "evidence.json"
    assert smoke.main(["--output", str(output)]) == 0
    evidence = json.loads(output.read_text())
    assert evidence["server"]["owned_process_stopped"]
    assert evidence["local_server_binary"]["version"] == "versionbuild"
    assert len(evidence["cases"]) == 7
    assert evidence["generation_parameters"]["thinking"] is False
    assert evidence["temporary_instance_removed"]


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_cli_rejects_unbounded_timeouts_without_starting_server(value):
    with pytest.raises(SystemExit) as raised:
        smoke.main(["--timeout", value])
    assert raised.value.code == 2


def test_owned_server_is_cleaned_up_on_startup_timeout(monkeypatch, tmp_path):
    class Process:
        pid = 123
        returncode = None
        terminated = 0
        def poll(self): return self.returncode
        def terminate(self): self.terminated += 1; self.returncode = -15
        def wait(self, **kwargs): return self.returncode
    process = Process()
    def absent(url): raise urllib.error.URLError(ConnectionRefusedError())
    monkeypatch.setattr(smoke, "_ready", absent)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    clock = iter([0.0, 1.0])
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError, match="readiness"):
        with smoke.local_server("http://127.0.0.1:8080", "server", "model", tmp_path/"server.log", startup_timeout=.5):
            raise AssertionError("Timed-out server must never be yielded")
    assert process.terminated == 1


def test_busy_existing_server_is_not_replaced_on_readiness_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "_ready", lambda url: False)
    def forbidden(*args, **kwargs): raise AssertionError("Must not replace a busy existing server")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    clock = iter([0.0, 1.0])
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError, match="readiness"):
        with smoke.local_server("http://127.0.0.1:8080", "unused", "unused", tmp_path/"server.log", startup_timeout=.5):
            raise AssertionError("Busy server must not be used")


@pytest.mark.parametrize("answer", ["COBALT47", "COBALT47."])
def test_free_text_marker_delivery_accepts_punctuation_without_repair(monkeypatch, answer):
    def native(self, endpoint, payload, **kwargs):
        response = fake_native(self, endpoint, payload, **kwargs)
        if response.get("content") == smoke.MARKER:
            response["content"] = answer
        return response
    monkeypatch.setattr(LlamaCppFastTransport, "_post_json", native)
    result = smoke.run_smoke(factory)
    row = next(row for row in result["cases"] if row["case"] == "cognitive")
    assert result["passed"] and row["passed"]
    assert row["raw_model_response"] == row["model_response"] == row["final_result"] == answer
    assert row["validation"]["semantic_marker_response"]
    assert row["validation"]["unrepaired_model_response"]
    assert row["counts"] == {"backend_attempts": 1, "backend_completions": 1,
                             "generation_requests": 1, "generation_responses": 1}
