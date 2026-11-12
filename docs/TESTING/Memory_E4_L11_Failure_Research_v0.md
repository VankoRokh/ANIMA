# ANIMA — E4-L1.1 Failure Research and Counterexample Plan v0

**Status:** research design; **not a benchmark result** and **no production changes**.  
**Basis:** [independent measured evaluation](Memory_E4_L1_Evaluation_Results_v0.md), frozen 57-case E4 v0 and its raw traces at Actions run #43171628756.

## Observed baseline problems

- **D01 / false Episode merge:** L0 Shadow groups e1/e2 in the same Episode on high raw token overlap; e3 explicitly reports two independent trials. L1 cannot correct derived grouping.
- **U05 / inflected noun phrase:** user says `чёрной коробочкой`, while the gold names `чёрная коробочка`. L1 stores source phrase but has no bounded grammatical key.
- **N01 / reported shared incident:** two device observations name outage A9, later source says both are from one case A9. L1 depends on a specific wording and abstains.
- **N04 / distinct ticket namespaces:** T77 in verified separate projects Alpha/Beta; L1 currently conflates known-different and uncertain namespaces, returning insufficient.

## L1.1 restricted architecture

1. **Derived Episode view, not rewriting Shadow:** include original L0 decisions unchanged and create `episode_view` with `base_assignments`, `effective_assignments`, `revision_proposals`. Split only when a credible **same-speaker, same-session, later explicit separation report** matches exactly two earlier uniquely labelled trial observations, tied to a versioned `setup.prior_projection`. Require the existing Shadow to have actually merged them. Assign a new local derived Episode ID to the latter trial; preserve raw Event IDs and memory-store snapshot. Expose clear **lab-only** status. Re-evaluation never asserts durable Memory rewrite.
2. **Alias morphology:** preserve source `surface`, add `surface_canonical` from a small declared Russian feminine-adjective + instrumental-noun grammatical normalizer; normalize both trace and expected surface using the same *predeclared* linguistic algorithm (not a literal gold synonym table). It never changes physical Entity identity or source authority.
3. **Story identity:** parse supported typed case markers for ticket, incident and outage references, then join only in an equivalent reporter+namespace. Attach both raw-source IDs; do not upgrade source report to fact.
4. **Known distinct namespaces:** `not_same_case_reported` only when the input contains an explicit, trusted fixture precondition for the **specific different namespaces** and matching case IDs. Mere difference in unverified text or an untrusted relay still yields `insufficient`.

## Counterexamples to write before accepting improvements

| Topic | Counterexample | Expected safe behavior |
| --- | --- | --- |
| Episode | Same experiment A described in two messages, then informal 'два теста' without verified separation | No split |
| Episode | Different labelled tests A/B, but third-party (not user) says they were independent | No untrusted resegmentation |
| Episode | Two tests A/B with no source-projection version/sources known | Candidate for review only; do not claim versioned applied revision |
| Episode | Correcting one grouped pair does not modify a third independent Episode or original L0 decisions | Only affected derived assignments change |
| Alias | 'большой коробкой' should not become an unrelated physical 'коробочка' | Normalization does not hallucinate a new Entity |
| Alias | Unknown mention with no user clarification | Never a confirmed mapping |
| Story | Two unrelated devices with the same word 'авария' but no incident ID | No mandatory Story link |
| Story | Ticket T77 repeated by an unverified relay | No user-scoped same-case verification |
| Namespace | Different project names without **verified** namespace-disjoint precondition | Preserve uncertainty |
| Namespace | Verified Alpha/Beta namespaces with T77 | Return scoped not-same-case only; no global claim |
| Integrity | A forged revision without trigger Event or unmatched source IDs | Evaluator rejects or returns NOT_OBSERVED, never PASS |
| Regression | Run the frozen 42+15 with identical gold and compare full per-check changes | No tuning of frozen gold, explicit regressions visible |

## Acceptance gates

- `L1` remains accessible, byte-identical algorithm and separately reproducible.
- `L1.1` is opt-in and explicitly marks any corrected Episode grouping as a temporary materialized laboratory view.
- Independent evaluator runs **after** closed raw trace and validates source IDs, status, L0 baseline, revised assignments and trusted setup preconditions. It does not import adapter.
- Compare old/new `PASS`/`FAIL`/`NOT_SUPPORTED`/`NOT_OBSERVED` counts as well as **per-case regressions**, not just headline pass rate.
- No migration, Knowledge admission, production memory write, scheduling or crash recovery claimed. No blinded holdout claim.
