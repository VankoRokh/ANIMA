# ANIMA v0.2 — R9.4.5b Targeted Remediation

Baseline `b3ce10767405b395541ea723116233ea8017a863`, branch `work/v02-e26-r9-remediation`. Основания: [R9.4.5a](e2-6-r945a-targeted-root-cause-v02.md), [R9.4.4](e2-6-r944-controlled-evaluation-v02.md), [R9 register](e2-6-r9-remediation-v02.md). A/B/D одобрены для opt-in laboratory implementation; C и verification I/O optimization отложены. R944-F01/F02 OPEN, r943/0.1 не stable.

## 1. Diagnostic design — до runtime changes

[Runner](../../labs/virtual_anima_lab/python/lifecycle/e26_r945_diagnostic.py) использует existing Q/I typed mapping/signatures и no-dispatch transport. Source proposal: `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r945a-2f0f5e6/diagnostic-proposal-NOT-RUN.json`; frozen request: R944 control-7-C03-00-A/wire/01-exchange.json#/request. Source SHA, payload hashes всех four cells, mapping/inverse validation и order заморожены до inference.

Cells: 0 old strategy/original ID; 1 new strategy/original ID; 2 new strategy/renamed ID; 3 old strategy/renamed ID. Native ID complete BIJECTIVE_RENAME; Event/Sample/source IDs неизменны. Existing strategy strings — единственный non-ID factor; остальные fields/bytes доказуемо восстанавливаются к original. N=20 counterbalanced blocks: even [0,1,2,3], odd [3,2,1,0], maximum80 calls, serial, один outstanding request. Generation settings/endpoint/model/backend preflight frozen до run; UNKNOWN fields не объявляются matched.

Analysis: within-block strategy effect при fixed ID (0/1 и 3/2), ID effect при fixed strategy (0/3 и 1/2). Tool/typed args, text stop, terminal, raw response hashes, usage и latency отдельно. Нет tool dispatch, retries, selective reruns или archived-response substitution. Transport/backend/config mismatch останавливает trial, failures остаются в planned denominator80; length/invalid terminals сохраняются. Один frozen context не превращается в20 independent scenarios; no full trajectory/generalized causal effect claim.

Evidence root `/home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r945b-b3ce107/`: diagnostic/, synthetic/, validation/ раздельны. Diagnostic design и synthetic checks фиксируются отдельным commit до inference; results/conclusions фиксируются до A/B/D changes. Full T-fresh не запускается в этом этапе.


### Diagnostic results — зафиксированы до runtime

Clean diagnostic implementation `868ec81b33e60b430818807ab3ec1260747ba975`; frozen manifest SHA-256 `7b49545beabd09d50e9dd2480c9193baf5e1dd27d32285917b206c8f07db5f08`. 80 planned/attempted/received, 0 failed; no dispatch/retry/rerun. Cell0 old/original: 19 lookup_raw_evidence +1 text stop. Cells1/2/3: по20 lookup. Typed operations/arguments equality: strategy-original-ID19/20, strategy-renamed-ID20/20; ID-old-strategy19/20, ID-new-strategy20/20. Text/terminal/raw/usage сохранены в отдельных sample/exchange records; decoder проверил tool schema/typed args, не выполняя операции.

Вывод: устойчивое ухудшение от new strategy в этом фиксированном request **не воспроизведено**; это не доказывает безвредность representation/IDs вообще, не устанавливает trajectory effect и не закрывает F01. Все80 сохранены, single stop не исключён. Cache/warm/slot state UNKNOWN; один context, никакого scenario-level significance/generalization. Backend executable/argv/model/PID/start/template pre/post matched в пределах сохранённых checks, environment/peer attestation отсутствует. `diagnostic/results-before-runtime.json` хранит результаты и ограничения до A/B/D.
