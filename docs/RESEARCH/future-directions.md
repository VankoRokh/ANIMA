# Аппаратные исследования и будущие направления

**Статус:** набор независимых исследовательских вопросов. Пункты здесь **не** являются обещанными Stage, датами или зависимостями для `ANIMA v0.1 Foundation`. Полная очередность работ задаётся только [Roadmap активного релиза](../roadmap.md).

## PC и Raspberry Pi 5

[TV-0054](../TESTING/Results/TV-0054.md) сохраняет пробы Core T6–T9.7 на PC и Pi: bounded Goal/Task, replay, настоящие детерминированные SIGKILL cutpoints для Core и профилирование. Итог `Inconclusive` относится к его точным условиям, частично внешним скриптам и состоянию checkout; **это не приёмка общей Foundation v0.1 на Pi** и не перенос E4 SIGKILL-доказательств на production Memory.

[Отдельный E4 scale gate](../TESTING/Memory_E4_Crash_Scale_Exit_Gate_v0.md) собрал CI synthetic 100/1000/10000 узлов на x86-64; Pi сопоставление на одинаковом workload остаётся открытым. Не использовать эти числа как SLO для постоянного агента.

## FAST/DEEP/SLEEP, perception и другие возможности

| Направление | Статус | Условие дальнейшего решения |
| --- | --- | --- |
| FAST/DEEP inference / LoRA | Изолированные Stage 5–7 и residual тесты; не входят в базовый headless | Independent holdout, стоимость, качество и явные права |
| SLEEP refinement / meta-memory | Базовый SLEEP Stage 3 и checkpoint имеют проверки; расширенная консолидация и self-investigation не приняты | Provenance, source identity, bounded checkpoints, безопасный resume |
| Датчики (камера, микрофон, Wi-Fi sensing, носимые устройства) | Возможные opt-in adapters | Trusted ingest, управление объёмом потока, энергобюджет и разрешения |
| Hardware/compute dock/accelerators | Исследование выбора ресурсов | Реальный workload с CPU/GPU/RAM/SSD и power профиль |
| Воплощение и поведение | Долгосрочная идея, не релизный контракт | Сначала переносимый программный экземпляр и безопасные action boundaries |

[Исходный журнал идей](../ROADMAP/Research.md) хранит непринятые предложения и старые даты. [Принципы Core](../system/README.md) не требуют разделять логические модули по физическим платам. Новая идея сначала получает протокол измерения и критерии отказа, а не обещание, что «следующий этап» уже утверждён.
