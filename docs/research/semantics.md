# Stage 7: Semantic Boundary и model residual

**Статус:** `classify_relation/0.1` — принятая **read-only** граница. Полный write/update/revision Knowledge lifecycle в историческом `project.json` — `Planned`. Frozen semantic profile — не разрешение обновлять факт или запускать Tool.

## Контракт и разделение ответственности

[Исходный Stage 7 boundary](../ROADMAP/Stage_7_Semantic_Boundary_v0.md) (решение 3 ноября): типизированный `Claim` с qualifiers/polarity/time, `Evidence`, `Source`, `Producer`, provenance, `EntityRef`/`PredicateRef`, `Value` и явный temporal scope.

`CONTENT` (`SUPPORT`, `CONTRADICTION`, `COMPATIBLE_DISTINCT`, `TEMPORAL_SUCCESSION`, `NOT_COMPARABLE`, `INSUFFICIENT`, `UNSUPPORTED`) и `REVISION` (`CORRECTION`) не должны слиться в одно универсальное `RESOLVED/UNRESOLVED`. Детерминированно решаемые facets остаются system-owned, модель получает только строго ограниченный residual. Даже правильная модельная классификация **не** выбирает lifecycle action.

## TV-0052 — детерминированный baseline

[TV-0052](../TESTING/Results/TV-0052.md), snapshot `ccb0fe72fb6686042bf5853489eda1e28e96981d`, `Passed`: frozen **50/50** reviewed roots, **48/50** zero-backend deterministic/preflight; два language-semantic residual `CR-028` и `CR-032`; process-error roots отдельно `CR-046–049`. Проверены type/protocol validator, deterministic evaluator, temporal, evidence dependence и запрет модельной перезаписи решения.

**Не доказаны** model quality, семантика записи Knowledge, production dispatcher, dependency reevaluation, LoRA/SFT.

## TV-0053 — model-facing residual

[TV-0053](../TESTING/Results/TV-0053.md), snapshot `6ad680b955158c53deb2b22420fdf0c9c0fb1bca`, итог **`Inconclusive`**. Qwen3-0.6B-Q8_0 и SmolLM3-3B-Q8_0 при `temperature=0`; сравнение четырёх evaluation-only случаев `CR-028`, `CR-032`, `CR-030-M`, `CR-050-M`.

| Протокол | Qwen3-0.6B | SmolLM3-3B | Вывод |
| --- | ---: | ---: | --- |
| `revision-residual/0.2` | 2/4 | 2/4 | Ошибки explicit и hedged correction |
| `revision-residual/0.3` без leakage системного `coverage` | 2/4 | 3/4 | Smol решил `CR-028`, оба не решили `CR-032` |
| `revision-factorized-diagnostic/0.1` (Qwen) | 0/4 accepted | Не проверено | Скопирован prompt pseudo-enum в поле `missing`, validator отверг |

**Принято для следующей оценки:** `revision-residual/0.3` остаётся baseline; текущий factorized diagnostic отклонён. Нельзя объявлять три из четырёх успешных классификаций универсальным качеством и нельзя тюнить prompt по тем же известным четырём случаям до отдельного holdout.

## Открытые DP и решение

`DP-08` — authority/lifecycle actions, `DP-09` — Knowledge read semantics, `DP-10b` — dependency reevaluation, `DP-11` — production integration. Все эти вопросы требуют отдельных контрактов и тестов; текущая v0.1 не зависит от их закрытия. [ADR-010](../DECISIONS/ADR-010_Stage_7_Semantic_Boundary.md) сохраняет первоначальное решение, [спецификация conformance](../TESTING/Stage7_Conformance_v0.md) — исходные сценарии.

**Не экстраполировать:** нет подтверждённой общей production semantic Memory и автономного исправления Knowledge.
