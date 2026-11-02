import pytest

from anima.cognition.fast_llm import (
    FastLLMCallResult,
    FastLLMModelOutputError,
    FastTextTransport,
    LlamaCppFastTransport,
    _final_answer,
)
from anima.cognition.llm_transport import (
    LLMCallResult,
    LLMModelOutputError,
    LlamaCppTransport,
    TextTransport,
    final_answer,
)


class RecordingSharedTransport(LlamaCppTransport):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.requests = []

    def _post_json(self, endpoint, payload, *, timeout_seconds):
        self.requests.append((endpoint, payload, timeout_seconds))
        if endpoint.endswith("/apply-template"):
            return {"prompt": "shared rendered prompt"}
        return {
            "content": "shared final answer",
            "reasoning_content": "hidden reasoning",
            "tokens_evaluated": 21,
            "tokens_predicted": 4,
            "stop": True,
        }


def test_shared_transport_is_role_neutral_and_returns_shared_result():
    transport = RecordingSharedTransport(
        base_url="http://127.0.0.1:9000/v1",
        model="replaceable-model",
        thinking=False,
        max_output_tokens=128,
        temperature=0.0,
        top_k=5,
        top_p=0.8,
        min_p=0.05,
    )

    call = transport.complete(
        system_prompt="system",
        user_prompt="user",
        timeout_seconds=30.0,
    )

    assert isinstance(call, LLMCallResult)
    assert call.model == "replaceable-model"
    assert call.text == "shared final answer"
    assert call.reasoning_chars == len("hidden reasoning")
    assert call.input_tokens == 21
    assert call.output_tokens == 4
    assert len(transport.requests) == 2
    assert transport.requests[0][0].endswith("/apply-template")
    assert transport.requests[1][0].endswith("/completion")


def test_shared_final_answer_removes_think_blocks_without_role_ownership():
    final, reasoning_chars = final_answer(
        "<think>private</think>\nanswer",
        role_label="TEST",
    )

    assert final == "answer"
    assert reasoning_chars > 0

    with pytest.raises(LLMModelOutputError, match="output limit"):
        final_answer("<think>unfinished", role_label="TEST")


def test_fast_compatibility_names_point_to_shared_contracts():
    assert FastLLMCallResult is LLMCallResult
    assert FastTextTransport is TextTransport
    assert issubclass(LlamaCppFastTransport, LlamaCppTransport)


def test_fast_wrapper_preserves_stage5_output_error_boundary():
    with pytest.raises(FastLLMModelOutputError, match="output limit"):
        _final_answer("<think>unfinished")
