"""Benchmark evaluator/transport tests; no real inference or model dependency."""
import json
from pathlib import Path
import urllib.error

import pytest

from anima.cognition.fast_llm import LlamaCppFastTransport
from scripts import benchmark_stage5_v2 as bench


def native(self, endpoint, payload, **kwargs):
    if endpoint.endswith('/apply-template'):
        assert payload['chat_template_kwargs'] == {'enable_thinking': False}
        return {'prompt': json.dumps(payload['messages'])}
    assert payload['temperature'] == 0 and payload['n_predict'] == 256
    view = json.loads(json.loads(payload['prompt'])[1]['content'].split('TASK_VIEW:\n')[1])
    answer = ('CONTINUE' if view['operation'] == 'CHOOSE_ACTION' else
              'AMBER' if view['operation'] == 'QUERY_FACT' else
              'amber.' if 'bicycle' in view.get('input', '') else 'COBALT47.')
    return {'content': answer, 'tokens_evaluated': 100, 'tokens_predicted': 4, 'stop': True}


def run(monkeypatch, callback=native):
    monkeypatch.setattr(LlamaCppFastTransport, '_post_json', callback)
    return bench.run_scenarios(lambda: bench.ObservedTransport(**bench.PARAMETERS))


def test_all_eight_scenarios_use_real_pipeline_and_separate_counts(monkeypatch):
    rows = run(monkeypatch)
    assert len(rows) == 8 and all(row['passed'] for row in rows)
    for row in rows[:3]:
        assert row['backend_attempts'] == row['generation_requests'] == row['successful_completions'] == 0
        assert row['input_tokens'] == row['output_tokens'] == 0
    assert rows[0]['final_result'] == '0.000001'
    assert rows[1]['route'] == 'INSUFFICIENT_DATA'
    assert rows[2]['resolution']['outcome'] == 'NO_ADMISSIBLE_ACTION'
    for row in rows[3:]:
        assert row['backend_attempts'] == row['generation_requests'] == row['successful_completions'] == 1
        assert row['route'] == 'COGNITIVE_REQUIRED'
        assert row['input_tokens'] == 100 and row['output_tokens'] == 4
    injected = rows[5]
    assert injected['raw_model_response'] == 'CONTINUE'
    assert injected['backend_response'] == 'SHUTDOWN'
    assert injected['candidate_validity'] is False and injected['invalid_output_rejection'] is True
    assert injected['fault_injection'] == 'replace_result_after_real_completion'
    assert rows[6]['projected_view']['evidence'][0]['value'] == "The user's bicycle is amber."
    assert rows[6]['context_budget'] == {'max_items': 6, 'max_chars': 1200}
    assert rows[7]['resolution']['reason'] == 'conflicting_or_multiple_facts'
    summary = bench.summarize(rows)
    assert summary['passes'] == 8 and summary['positive_model_passes'] == 4
    assert summary['backend_attempts'] == summary['generation_requests'] == summary['successful_completions'] == 5
    assert summary['input_tokens'] == 500 and summary['output_tokens'] == 20
    json.dumps(rows, allow_nan=False)


@pytest.mark.parametrize('text', ['CONTINUE.', 'RESULT=CONTINUE', 'SHUTDOWN'])
def test_invalid_real_candidates_are_never_repaired_or_retried(monkeypatch, text):
    def wrong(self, endpoint, payload, **kwargs):
        response = native(self, endpoint, payload, **kwargs)
        if response.get('content') == 'CONTINUE': response['content'] = text
        return response
    rows = run(monkeypatch, wrong)
    row = rows[4]
    assert not row['passed'] and row['candidate_validity'] is False
    assert row['invalid_output_rejection'] is True and row['final_result'] is None
    assert row['raw_model_response'] == text and row['generation_requests'] == 1


@pytest.mark.parametrize('text', ['text', 'candidate', 'output_contract', 'unrelated'])
def test_label_echo_or_missing_marker_fails_semantic_delivery(monkeypatch, text):
    def wrong(self, endpoint, payload, **kwargs):
        response = native(self, endpoint, payload, **kwargs)
        if response.get('content') == 'COBALT47.': response['content'] = text
        return response
    row = run(monkeypatch, wrong)[3]
    assert row['raw_model_response'] == row['final_result'] == text
    assert not row['correctness'] and not row['passed']


def test_model_failure_keeps_raw_tokens_audit_and_route(monkeypatch):
    def broken(self, endpoint, payload, **kwargs):
        response = native(self, endpoint, payload, **kwargs)
        if endpoint.endswith('/completion'): response['content'] = '<think>unfinished'
        return response
    rows = run(monkeypatch, broken)
    for row in rows[3:]:
        assert not row['passed'] and row['failure_classification'] == 'MODEL_OUTPUT'
        assert row['route'] == 'COGNITIVE_REQUIRED'
        assert row['backend_attempts'] == row['generation_requests'] == 1
        assert row['successful_completions'] == 0 and row['output_tokens'] == 4
        assert row['raw_model_response'] == '<think>unfinished'


def test_template_transport_failure_has_no_generation_or_fabricated_tokens(monkeypatch):
    def broken(*args, **kwargs): raise ConnectionError('offline')
    rows = run(monkeypatch, broken)
    for row in rows[3:]:
        assert row['backend_attempts'] == 1 and row['generation_requests'] == 0
        assert row['successful_completions'] == 0 and row['input_tokens'] is None
        assert row['failure_classification'] == 'TRANSPORT' and not row['passed']


def test_inventory_is_complete_v1_set_and_not_qwen_1_7():
    text = Path('docs/TESTING/Tool_Model_Comparison.md').read_text()
    names = [line.split('|')[1].strip() for line in text.splitlines()
             if line.startswith('| ') and 'Q8_0' in line]
    assert list(bench.MODELS) == names
    assert len(names) == 8


def test_owned_server_busy_port_never_spawns(monkeypatch, tmp_path):
    monkeypatch.setattr(bench, 'get_json', lambda url: {'status': 'ok'})
    def forbidden(*args, **kwargs): raise AssertionError('must not start or stop another server')
    monkeypatch.setattr(bench.subprocess, 'Popen', forbidden)
    with pytest.raises(RuntimeError, match='occupied'):
        with bench.model_server('binary', Path('model'), 'alias', tmp_path, 8081): pass


def test_owned_server_failure_is_always_cleaned_up(monkeypatch, tmp_path):
    class Process:
        pid = 123
        stopped = False
        def poll(self): return 0 if self.stopped else None
        def terminate(self): self.stopped = True
        def wait(self, **kwargs): return 0
    process = Process()
    calls = 0
    def get(url):
        nonlocal calls
        calls += 1
        if calls == 1: raise urllib.error.URLError(ConnectionRefusedError())
        if url.endswith('/health'): return {'status': 'ok'}
        if url.endswith('/v1/models'): return {'data': [{'id': 'alias'}]}
        return {'model_path': str(Path('model').resolve())}
    monkeypatch.setattr(bench, 'get_json', get)
    monkeypatch.setattr(bench.subprocess, 'Popen', lambda *a, **kw: process)
    with pytest.raises(ValueError, match='caller'):
        with bench.model_server('binary', Path('model'), 'alias', tmp_path, 8081) as info:
            raise ValueError('caller')
    assert process.stopped and info['owned_process_stopped']


def test_cli_saves_every_model_and_does_not_touch_v1(monkeypatch, tmp_path):
    from contextlib import contextmanager
    import subprocess
    monkeypatch.setattr(LlamaCppFastTransport, '_post_json', native)
    models = tmp_path/'models'
    for relative in bench.MODELS.values():
        path = models/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fake-gguf')
    @contextmanager
    def server(binary, model, alias, output, port):
        info = {'base_url': 'http://127.0.0.1:8081', 'owned_process_stopped': False}
        try: yield info
        finally: info['owned_process_stopped'] = True
    monkeypatch.setattr(bench, 'model_server', server)
    monkeypatch.setattr(bench.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess([], 0, 'fake version', ''))
    v1 = Path('.benchmarks/tool-models/comparison.csv')
    before = v1.read_bytes() if v1.exists() else None
    output = tmp_path/'results'
    assert bench.main(['--models-root', str(models), '--server-binary', __file__, '--output-dir', str(output)]) == 0
    reports = json.loads((output/'comparison.json').read_text())
    assert len(reports) == 8
    assert all(r['summary']['passes'] == 8 for r in reports)
    assert all(r['server']['owned_process_stopped'] for r in reports)
    assert len(list(output.glob('*/evidence.json'))) == 8
    assert before == (v1.read_bytes() if v1.exists() else None)


def test_v1_reference_uses_raw_fifty_run_denominator(tmp_path):
    path = tmp_path/'comparison.csv'
    path.write_text('model,total_runs,passes,errors,run_id,mean_pass_latency_ms\n'
                    'SmolLM3,50,15,10,representative,93228\n'
                    'SmolLM3,10,9,0,later-smoke,1\n')
    result = bench.v1_reference(path)['SmolLM3']
    assert result['passes'] == 15 and result['total'] == 50 and result['errors'] == 10
    assert result['run_id'] == 'representative'
