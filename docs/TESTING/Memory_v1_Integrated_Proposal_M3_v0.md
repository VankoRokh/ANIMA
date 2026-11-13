# ANIMA v0.1 Integrated — M3 memory-sourced Goal suggestion preview

**Status:** CI VERIFIED — full Python 3.12/3.13/3.14 regression and two-process M3 preview PASS; owner-reported laptop M3 PASS on Python 3.14.4; Raspberry Pi deferred. **Branch:** `work/anima-v01-integrated-m3` from M2 laptop PASS at `fbe34df8400fed7bfc6c23394f517a46e9a5ee7f`. No Raspberry Pi work in this phase.

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

### GitHub CI — 2026-11-13

- **Frozen executable snapshot:** `544c284a56e77029c58f798bc66da886f0438c5b`. [GitHub Actions run #43427875816](https://github.com/VankoRokh/ANIMA/actions/runs/43427875816) — **SUCCESS** on all three Linux x86-64 Python jobs.
- **Targeted M0/M1/M2/P6/M3:** **32/32 PASS** each on Python **3.12, 3.13 and 3.14**.
- **Full repository regression:** **1679/1679 PASS** each on Python **3.12, 3.13 and 3.14**; documentation and syntax checks PASS.
- **Two-process standalone acceptance:** `M3_GOAL_PREVIEW_PASS` on every Python version, with `request=REVIEW_REQUIRED`, `state_only=REJECTED`, `conflict=CONFLICT_REVIEW`.
- Negative checks include forged memory/source IDs, self-citation, wrong current query, unsupported template, extra tool/role/priority/Goal fields, oversize rationale, stale view, Memory rewritten after capture, partially indexed or altered source, and an unbound historical state report. A selected historical report **never** gives world/goal/approval authority.
- The runner verifies **actual** GoalStore count, TaskStore emptiness, ExecutionStore emptiness, virtual door world effect ledger and real Knowledge table count are all zero. Existing Stage 6 model `ProposalValidator` still rejects `PROPOSE_ACTION`, `PROPOSE_TASK`, `REQUEST_CONTEXT`.
- M3 uses only synthetic marker recognition. It does not run a real LLM or live Godot, establish natural-language semantic correctness, approve a proposal, or create any Goal. Full M2 live Godot PASS remains a **separate previous gate**.

**Initial test remediations:** the first M3 CI runs detected (1) a literal newline escape introduced by a test-side edit; (2) a partial-index negative test that modified the persisted history later compared after restart; and (3) artifact output located inside the repository despite the runner's external-report guard. All were addressed in **test/lab/CI code** without changing `anima/` or weakening source/authority validation. Last complete matrix #43427875816 is green.

### Notebook acceptance — owner-reported PASS

From the root of a separate M3 worktree with Python 3.14.4:

```bash
python -m scripts.run_memory_v1_goal_proposal_gate --report /tmp/anima-m3-PC.json
```

The runner uses three temporary isolated synthetic headless worlds with a configured but inactive Core action boundary. It does not require running Godot. The report file must not exist before this call. **Only a real owner-provided JSON** with `M3_GOAL_PREVIEW_PASS` can close M3 on that physical laptop. Raspberry Pi remains deferred.

### Owner's notebook report — 2026-11-13

**Evidence:** original file `anima-m3-PC.json` supplied by the owner, independently parsed after upload. This is a **reported local-run result**, not a remote terminal capture by the reviewer. The JSON has **no `commit` field**, so exact local Git SHA cannot be independently confirmed from this artifact alone; it does show schema `anima.memory_v1.goal_suggestion_m3/0.1` and the expected M3 result structure.

- **Environment:** Linux x86_64, Python `3.14.4`; `status=M3_GOAL_PREVIEW_PASS`. All three child-process verification phases report `M3_CASE_PASS`.
- **`request`:** `REVIEW_REQUIRED` with reason `historical_report_only_not_authorization`; one historical Memory ID and linked raw Event ID. Reported ten negative outcomes: fake Event/Memory, foreign template, fabricated Goal, operator-role claim, excess priority, tool escalation, oversized rationale, self-citation and wrong query.
- **`state_only`:** `REJECTED` / `no_proposal`; forged draft based only on a state report rejected as `source_does_not_request_target`.
- **`conflict`:** `CONFLICT_REVIEW` / `visible_revocation_requires_independent_review`; two historical raw Event IDs. No authorization conveyed by the conflict outcome.
- **For all cases:** `source_backed=true`, `review_is_approval=false`, `current_event_self_cited=false`, `current_event_persisted=false`, **0 Goal**, **0 Task**, **0 Action**, **0 Knowledge**.
- **Not tested by this local report:** `llm_used=false` in all cases; `godot_tested=false`, `pi_tested=false`, `production_code_changed=false`. M3 reports no natural-language understanding, independent operator approval or live-Godot action.

**Decision:** M3 review-only functional acceptance on the owner's laptop **PASS**. The boundary is deliberately non-authorizing and uses deterministic synthetic markers. M4, if undertaken, requires an independently specified and audited proposal→operator-approval→Core Goal transition. No official Stage completion is inferred.

**Next design question:** whether a later M4 should provide an explicit, auditable system/owner approval workflow that can convert a reviewed suggestion to a new Core Goal *without* weakening typed Goal binding, Proof and source-authority rules. M3 itself deliberately stops at review.

