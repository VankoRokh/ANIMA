# Stage 7 Conformance Corpus — Owner Review Log

Status: **Active review log.** This file records owner decisions for the draft root corpus before it is frozen as conformance gold.

Corpus: [Stage7_Conformance_Corpus_v0_Draft.md](Stage7_Conformance_Corpus_v0_Draft.md)

## Review status

| Block | Cases | Status | Decision date |
|---|---:|---|---|
| A — Atomic CONTENT relations | CR-001…CR-016 | **Accepted** | 2026-11-03 |
| B — Temporal CONTENT relations | CR-017…CR-026 | Pending review | — |
| C — REVISION / correction | CR-027…CR-034 | Pending review | — |
| D — Evidence identity / replay / dependence | CR-035…CR-040 | Pending review | — |
| E — Comparability / sufficiency / capability | CR-041…CR-045 | Pending review | — |
| F — Protocol / boundary / security | CR-046…CR-050 | Pending review | — |

Current progress: **16 / 50 root cases accepted.**

## Accepted Block A invariants

The owner accepted CR-001…CR-016 without semantic changes. In particular:

- exact same proposition in a provably common scope classifies as `SUPPORT`;
- incompatible values/polarity for a single-valued proposition in the same effective scope classify as `CONTRADICTION` without selecting a truth winner;
- compatible distinct values remain `COMPATIBLE_DISTINCT` where cardinality/polarity permits coexistence;
- different canonical entities are `NOT_COMPARABLE(DIFFERENT_ENTITY)` even when value text matches;
- partial wider evidence coverage does not prevent a local pair relation when the grounds required for that pair are present;
- `boolean false` is not silently rewritten as negative proposition polarity;
- source/model confidence, prestige and receipt/creation order do not determine semantic truth.

No accepted Block A case grants Knowledge status, source authority or lifecycle action.
