# ANIMA v0.1 Integrated — M3 memory-sourced Goal suggestion preview

**Status:** FROZEN CONTRACT before test implementation. **Branch:** `work/anima-v01-integrated-m3` from M2 laptop PASS at `fbe34df8400fed7bfc6c23394f517a46e9a5ee7f`. No Raspberry Pi work in this phase.

## Purpose

M0–M2 proved real persistence, read-only history, registered world observation, Core-owned action/Verification, and recovery. **None** let remembered information influence the *content* of a candidate goal. M3 is the narrowest measurable next step: model-replaceable backend reads real, source-backed historical Memory, emits an **untrusted draft goal suggestion**, then a separate system-owned read-only reviewer checks the draft and returns a structured review ticket.

M3 **must not** enable the existing `anima.cognition.proposals.ProposalValidator` for `PROPOSE_TASK`, `PROPOSE_ACTION` or `REQUEST_CONTEXT`; the Stage 6 production validator remains RESPOND-only. **A review ticket is not a Goal, Task, executable candidate, operator approval or trusted world observation.** No code automatically transfers a draft to `GoalStore`, `CoreIngress` or `CoreDoorExecution`.

## Experimental vocabulary (fixtures only)

One frozen suggestion template `suggest.ensure_virtual_door_closed/0.1`, one registered door subject and expected `closed`. The deterministic fixture backend emits a draft only if the selected historical source text contains exact marker `M3_REQUEST_DOOR_CLOSE`. `M3_REPORT_DOOR_CLOSED` is *not* a request, and `M3_REVOKE_DOOR_CLOSE` visibly challenges a request. These markers are **synthetic, test-only protocol labels**, not natural-language understanding, authority, reliability or semantic extraction. A real LLM is deliberately not used.

For each suggestion: an exact chosen Memory ID and raw Event ID must be present in the bounded captured Context and be verified against Event Retrieval's indexed raw bytes + provenance links. A requester cannot provide tool name, priority, Goal ID, permission, arbitrary target or an invented source. The system reads all **visible selected** source Events to detect a fixture conflict; it never asserts global absence of contradictory events beyond bounded retrieval coverage.

The reviewer outputs only `REVIEW_REQUIRED`, `CONFLICT_REVIEW`, or `REJECTED`; even `REVIEW_REQUIRED` is **never** execution authorization. No `Goal` or `Task` or tool effect may occur in any M3 case. The system may later design a separately owned operator approval and typed binding interface, but not silently add one here.

## Frozen acceptance corpus

| Case | Source/draft | Expected disposition | Reason |
| --- | --- | --- | --- |
| A | Real `M3_REQUEST_DOOR_CLOSE`, exact selected Memory + raw Event | `REVIEW_REQUIRED` | source-backed untrusted recommendation for human review |
| B | Only `M3_REPORT_DOOR_CLOSED` or no request | `REJECTED` | unsupported semantics; no goal from state assertion |
| C | Request + `M3_REVOKE_DOOR_CLOSE` both visible | `CONFLICT_REVIEW` | explicit conflict, never auto-activate |
| D | Hallucinated source ID or Memory ID | `REJECTED` | no verified provenance |
| E | Current query Event or unselected Memory as source | `REJECTED` | cannot self-cite or elevate unseen sources |
| F | Extra authority fields (`tool`, `priority`, `role`, `goal_id`) / unsupported template | `REJECTED` | strict schema/target allowlist |
| G | Incomplete Event index, tampered raw Event, stale Memory | `REJECTED` | fail closed, never use partial or modified evidence |
| H | Independent Python process restart | same source-backed review | no Goal, Task, world effect, Knowledge creation |

**Important:** a provenance link proves a report was recorded, **not** that the claim is true or that the speaker has permission to request the action. A query snapshot is obtained **before** any current input is committed. The rule-based fixture's exact marker matching does not solve ambiguity or contradiction in general natural language.

## Review and implementation boundaries

- `labs/virtual_anima_lab/python/m3_goal_preview.py` — experimental immutable view and read-only scope/evidence gate. **Not** part of production `anima/`.
- `scripts/run_memory_v1_goal_proposal_gate.py` — read-only synthetic history end-to-end / independent process gate and JSON evidence.
- `tests/test_memory_v1_goal_proposal_gate.py` — positive and negative tests; existing Stage 6 `ProposalValidator` rejection explicitly tested.
- CI: Python 3.12–3.14, targeted M0–M3 and full suite, `scripts/check.sh`.
- No M3 live Godot side effect: M2 is the existing validated external execution boundary. We intentionally stop **before** generating an executable goal.
- No production code, official Stage status, `docs/project.json`, new LLM, SLEEP, graph store, authority or Power/Linux hardware assumptions.

**Stop rule:** any automatic Goal/Task creation, effect, Knowledge confirmation, use of a user claim as registered `Belief`, unverified Event ID, accepted foreign template/authority field, or green test requiring suppression of frozen Stage 6 policy is a hard failure.

## Evidence

Results will be entered here only after observed CI and notebook tests. Passing CI alone does not mean physical laptop M3 PASS.
