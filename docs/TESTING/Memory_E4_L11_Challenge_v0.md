# ANIMA — E4 L1.1 Novel Adversarial Challenge v0

**Status: PREDECLARED / VISIBLE DEVELOPMENT CHALLENGE, NOT A BLINDED HOLDOUT.**  
**Source baseline:** E4 L1.1 as of commit `bccd84554f61c386faf563d618777be23c832192`.  
**Inputs:** [15 newly authored cases](Fixtures/memory_e4_l11_challenge_inputs_v0.json).  
**Gold:** [16 proposed scoped checks](Fixtures/memory_e4_l11_challenge_gold_v0.json), pinned separately before first execution.  
**Manifest:** [exact byte fingerprints](Fixtures/memory_e4_l11_challenge_manifest_v0.json).  
**Runner:** [challenge input-only adapter](../../labs/exp009/e4_l11_challenge_runner.py).  
**Post-hoc scorer:** [challenge evaluator](../../labs/exp009/e4_l11_challenge_evaluator.py).

## Why this is not the frozen E4 v0 corpus

The existing E4 v0 contains 57 visible, frozen cases with 122 checks. It showed zero FAIL in a *small observed subset* for L1.1. These 15 challenge cases are **new**, intentionally not drawn from that set, and explicitly target misleading shortcuts. They were authored **in the same development process** after observing implementation behavior; they cannot establish independent generalization even though their inputs and expected outputs were pinned before execution.

The challenge uses 36 new synthetic Events with unique IDs. Each case is isolated in temporary SQLite by the existing Shadow adapter. The evaluator does **not** call the adapter and loads its separate gold only after checking the completed raw trace, source IDs, provenance and declared fixture fingerprints. Evaluation FAIL is an **empirical result**, not a CI failure, whereas fake references and incorrect artifact structure fail CI.

## Predeclared case coverage

| Cases | Risk |
| --- | --- |
| X01–X05 | One marker across differing case/ticket types; distinct/unknown namespaces; untrusted relay; verified distinct namespaces; shared incident |
| X06–X08 | Two contradictory definitions for an alias in one session; anchored vs unanchored reuse; attempted alias promotion from external relay |
| X09–X10 | Bounded two-word Russian grammatical normalization vs a new three-word phrase |
| X11–X15 | Irrelevant later correction, explicit correction, untrusted correction, missing prior projection, duplicate trial labels |

## Commands

```bash
mkdir -p e4-l11-challenge
python -m labs.exp009.e4_l11_challenge_runner --output e4-l11-challenge/raw.json
python -m labs.exp009.e4_l11_challenge_evaluator --trace e4-l11-challenge/raw.json \
  --output e4-l11-challenge/assessment.json --print-summary
```

**Interpretation:** reports are scoped to `PASS`, `FAIL`, `NOT_SUPPORTED`, `NOT_OBSERVED`. Do not rewrite pinned gold to improve a score. No authority, actual external effects, durable Memory or crash/replay conformance is tested here. All existing frozen E4 v0 bytes remain unchanged.
