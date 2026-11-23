# ANIMA v0.2.0-rc.1 — запись о публикации Release Candidate

**Тип:** Release Candidate / GitHub Pre-release, **не** stable v0.2.  
**Одобрение владельца:** 19 ноября 2026 года.  
**Опубликован в GitHub:** 19 ноября 2026, 20:13:06 UTC (20 ноября, 00:13:06 по времени Тбилиси).  
**Независимый аудит:** H5.8 — `PASS / APPROVE_RC` в ограниченном доверенном профиле.  
**Публикация:** [GitHub Release `v0.2.0-rc.1`](https://github.com/VankoRokh/ANIMA/releases/tag/v0.2.0-rc.1).

## Зафиксированная ревизия

| Поле | Значение |
| --- | --- |
| Кодовый commit | `1364e62634669ef553df0b2f2d7a1159d404383f` |
| Git tree | `e8b2dda15b265185990b3010041f821ffdc765dd` |
| Аннотированный tag | `v0.2.0-rc.1` |
| Git tag object | `02c4b2e1fe9c956e21ff4ccbb54217905b95f641` |
| Release branch | `release/v0.2.0-rc.1` (кодовый SHA не изменён) |
| Release status | `published`, `prerelease=true`, `draft=false` |

Git tag object указывает на указанный commit, **не** на коммиты документации. Новые редакционные страницы расположены в ветке `docs/v0.2.0-rc.1-record`, не включены в зафиксированный тег. Запрещено передвигать или переписывать опубликованный тег ради документации.

## Что принято

Детерминированный профиль ANIMA развивает основание v0.1: каноническое Raw происхождение, Memory и Recovery, Evidence/Knowledge lifecycle, half-open temporal intervals, Retrieval/Context, структурную валидацию custom Retrieval adapters и предсказуемый rollback. R8.0–R8.3 закрыли три формальные находки H5.7.

| Acceptance | Результат |
| --- | --- |
| Полный pytest в кодовом checkout | **2315 PASS** |
| Независимый H5.8 на exact snapshot | **PASS / APPROVE_RC**, 2315 PASS |
| Оригинальные H5.7 formal probes | **62 PASS** на H5.8 (6 FAIL / 56 PASS на старом H5.7) |
| Новые независимые проверки | **235 PASS** |
| H57-01, H57-02, H57-03 | **FIXED_VERIFIED** |
| Контроль R7/H56/NEW/F инвариантов | Без обнаруженной контрактной регрессии в проверенных границах |

## Ограничения — условия применения RC1

- **O58-01:** отдельный Memory ID не удостоверяет независимое новое Raw свидетельство.
- **O58-02:** корректная структура Retrieval adapter не гарантирует достоверный канонический текст под известным ID.
- Использовать **доверенные** Memory/Raw writers и Retrieval adapters.
- Не заявлены automatic Knowledge aging, immutable historical Memory text, hostile SQL security, глобальная freshness `candidate=None`, power-loss/cross-file atomicity, real legacy migrations, Pi/ARM64 latency, LLM inference или универсальная автономия.

## Где находится нормативное описание

Этот файл — **публикационная карточка** и указатель, а не второй независимый контракт.

- [Контракт v0.2 RC1](../versions/v0.2/contract.md) — что входит и что не гарантируется.
- [Приёмка v0.2 RC1](../versions/v0.2/acceptance.md) — точные SHA, тесты, независимое заключение, зафиксированные границы.
- [Release notes v0.2 RC1](../versions/v0.2/release-notes.md) — описание функций и ограничения.
- [Раздел версий](../versions/README.md) — общий реестр.
- [Релиз v0.1 Foundation](../versions/v0.1/release-notes.md) — предыдущая стабильная основа.

**Граница релизной фиксации:** RC1 опубликован; окончательный stable v0.2 пока **не объявлен**. Следующие функции и исследования — вне этого тега.
