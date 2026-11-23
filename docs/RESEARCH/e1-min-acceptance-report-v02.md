# ANIMA v0.2 — независимая интеграционная приёмка E1-min

**Решение:** **`PASS_LAB_RESTRICTED`** — допускается только изолированный лабораторный контур E1.1–E1.4. **Никакого release approval, Core admission или готовности E2 «из коробки».**  
**Дата:** 23 ноября 2026 года.  
**Неподвижный целевой snapshot:** `3a922429aa00e439495346c140048e484c867cb4` (`work/v02-e14-operation-ledger`).  
**Независимые тесты, проверенный audit SHA:** `e928e92eed3dae721792a096bfbfecb1eda39fd7`.  
**CI:** [GitHub Actions 45167094963](https://github.com/VankoRokh/ANIMA/actions/runs/45167094963), все **5/5 jobs SUCCESS**, raw artifacts `anima-e1min-independent-blackbox` и `anima-e1min-prior-gates`.  
**Репозиторий:** `VankoRokh/ANIMA`; аудиторская ветка `audit/v02-e1min-independent-acceptance`; [замороженное техническое задание](e1-min-acceptance-brief-v02.md).

## 1. Независимость и методика

Аудиторские инструменты добавлены **поверх неизменённого** E1.4 baseline. В diff от `3a922429a...` только `tests/e1_min_independent_live_audit.py`, исследовательская документация и GitHub Actions. Файлы `anima/`, `labs/virtual_anima_lab/godot/LifecycleWorld.gd`, Python DTO, recovery/readback, release tag и прежние исторические доказательства **не изменены**. Этот метод означает независимые *проверки на замороженном коде*, а не внешнего человеческого эксперта.

Новый harness выполняет реальные TCP-запросы к отдельным Godot-процессам и **не использует** внутренние методы мира для успеха. Сценарий строится из чистой лабораторной конфигурации, с двумя разными маршрутами и seed 7/8. Скрытая карта, заготовленный маршрут и operator.inspect не передаются ANIMA/модели: маршрут выбирает **сам тестовый harness**. Доверие к наблюдениям пока ограничено лабораторным источником.

Параллельно воспроизведён frozen E1.4 native/live suite, P5/P6, M2 и полная Python-регрессия.

## 2. Результаты приёмки

| IM | Критерий | Фактический результат |
| --- | --- | --- |
| IM-01 | Три разных режима полномочий | **PASS**: `observe` / `observe, act` / `observe, act, operation_status`; эффекты/status не появляются раньше opt-in |
| IM-02 | Агентский порт не даёт операторские команды и скрытые сенсорные данные | **PASS для заявленной роли agent**; **известная уязвимость роли** отдельно воспроизведена в §3 |
| IM-03 | Два реальных обхода и `drop` в delivery | **PASS**: seed 7/8 × top/bottom = **4 завершённых маршрута**, по **15 `VERIFIED_SUCCESS`** каждый |
| IM-04 | Заблокированный прямой проход | **PASS**: по **1 `VERIFIED_BLOCKED`** на маршрут, без незаметного изменения позиции |
| IM-05 | Реальный TCP-send с непрочитанным ответом и восстановление | **PASS**: reconnect → `RECORDED` → оригинальный receipt + новый sensor proof |
| IM-06 | Replay, ID collision и spoofed status | **PASS**: 0 новых эффектов и clock changes при replay, `OPERATION_CONFLICT` для другого payload в `act` и `operation_status` |
| IM-07 | Внешнее изменение после чтения | **PASS**: operator obstacle увеличил revision, прежний intent отвергнут, status `UNKNOWN` не провоцирует повтор |
| IM-08 | Receipt нельзя самостоятельно превратить в успех | **PASS**: поддельный `owner` и `replayed=true` не дают `VERIFIED_SUCCESS` |
| IM-09 | Reset и перезапуск Godot-процесса | **PASS в рамках честной границы**: другая epoch/world incarnation, old status `UNKNOWN`, old action `EPOCH_CHANGED` или `WORLD_CHANGED`; нет ложной durable recovery |
| IM-10 | Bounded ledger / capacity | **PASS**: black-box TCP поместил 256 терминальных `BLOCKED`; 257-я операция получила `OPERATION_CAPACITY`, первая запись и replay сохранены, эффектов 0 |
| IM-11 | Полная совместимость E1/P5/P6/M2 | **PASS**: 2356 pytest на Python 3.12, 3.13, 3.14 и Godot job; E1.2/E1.3/E1.4 native/live, P5-C replay, M2 PASS |
| IM-12 | Отсутствие переписывания проверяемой реализации | **PASS**: исходный world/production baseline unchanged; отклонённые промежуточные CI runs сохранены |

Дополнительные сведения: **5/5 GitHub Actions jobs SUCCESS**; официальный Godot `4.7.2.stable.official.ed1daf0bf`, Ubuntu x86_64, Python 3.12.16 / 3.13.18 / 3.14.10. Проверка docs на коде до этого отчёта: **188 страниц / 1349 локальных ссылок, PASS**. Отдельные сырые world trace (capability modes, 4 routes, 256-capacity, role probe, restart) доступны в CI artifacts.

**Суммарно:** 4 × 15 = **60 подтверждённых успешных операций** в независимых маршрутах, 4 подтверждённые блокировки и 4 случая восстановления потерянного ответа. Это не производительность или обучение ANIMA, а воспроизводимый тест детерминированного виртуального контура.

## 3. Находки и обязательные ограничения

### E1MIN-01 — самообъявленная операторская роль, `HIGH` при переходе к E2

**Подтверждено отрицательным тестом.** Один и тот же локальный клиент получает `FORBIDDEN` на `agent.inspect`, но после смены заявленного поля `role` на `operator` получает закрытый `seed` и `walls` через `inspect`. Реального механизма аутентификации/разделения полномочий сокета нет.

- **Решение для E1-min:** допускается **только** изолированный лабораторный профиль, при котором код модели не имеет прямого сокетного доступа и изменить роль может лишь доверенный harness.
- **Блокер перед небезопасным E2/production:** FAST, Retrieval и любые недоверенные плагины не могут получать raw socket или самостоятельно формировать `role`. Нужен один доверенный Core-owned admission/adapter с фиксированными capabilities и проверяемой связью с наблюдателем, отдельный тест на подмену оператора и запрет обходных API.
- `WorldObservation.source_ref` валидирует форму поля, **не аутентифицирует** источник. В E2 требуется canonical Raw provenance и привязка реального world port к зарегистрированному сенсору.

### E1MIN-02 — volatile ledger и `UNKNOWN`, `ACCEPTED LAB LIMIT`

После reset или перезапуска Godot старый receipt не восстанавливается. `UNKNOWN` остаётся неопределённостью, а не безопасной инструкцией повторять операцию. **Exactly-once между incarnations не доказано**. В E2 можно испытать reboot Core с тем же **работающим** Godot, но нельзя обещать E4 world persistence или восстановление после выключения питания.

### E1MIN-03 — неполная автономия, `ACCEPTED RESEARCH LIMIT`

Нет интегрированного `event→Raw Memory→Context→candidate→Core admission→action→proof→event`. Действия генерировал harness. Не проверялись цель/задача Core, независимый admission, устойчивость пользовательской памяти, реальная FAST, энергия, зарядка или самоинициированное исследование. Это обязательная работа E2 и последующих экспериментальных шагов, **не** недостаток узкого E1-min.

### E1MIN-04 — ограниченная fault injection, `ACCEPTED LAB LIMIT`

Действие действительно отправлялось через TCP, после чего ответ намеренно **не читался**, а сокет закрывался. Это **не** проверка произвольных потерь TCP-пакетов, настоящего `SIGKILL` между effect и commit, отключения питания либо долговременной записи. Для таких сценариев нужны другие фазы исследования и иные гарантийные контракты.

## 4. История CI и честный статус

Ранний run [45166643330](https://github.com/VankoRokh/ANIMA/actions/runs/45166643330) обнаружил **ошибки аудиторской инфраструктуры**, а не дефекты ANIMA: неверный whitelist path (`.github`) и отсутствующий `PYTHONPATH` у отдельного скрипта. Скрипты/CI исправлены без изменения проверяемого исходного кода. Проверочный run [45166813496](https://github.com/VankoRokh/ANIMA/actions/runs/45166813496) дал первый black-box PASS. После добавления отрицательного role-spoof probe выполнен итоговый [45167094963](https://github.com/VankoRokh/ANIMA/actions/runs/45167094963): **5/5 PASS**.

Не подменять результаты ранних failed/cancelled runs и не выдавать ограниченную приёмку за полную проверку автономного ИИ.

## 5. Решение о переходе

**Принять E1-min с вердиктом `PASS_LAB_RESTRICTED`** только в `docs/RESEARCH/`. Не изменять релиз `v0.2.0-rc.1`, не объединять PR автоматически. Исходный snapshot остаётся воспроизводимым.

**Следующий этап — E2, но начать с доверенной границы**, а не с LLM:
1. E2.1: один Core/Stage6 authority path, регистрация world source, отдельный typed adapter, явная изоляция операторского порта, deny-by-default и аудит обходных API.
2. E2.2: документируемое и durable отображение каждого `WorldObservation` в canonical Raw Event с world/epoch/sample и provenance, без поддельного Knowledge.
3. E2.3: Core-issued bounded candidates; детерминированный FAST-stub выбирает только ID или `NO_ADVICE`, не отдаёт `WorldAction` напрямую.
4. E2.4: durable decision-before-effect record, `Goal/Task`, admission и verifier после action/readback.
5. E2.5: process restart Core при живом Godot, ledger reconciliation `RECORDED/UNKNOWN`, fail-closed new epoch/world.
6. E2.6: повторения, отрицательные тесты, независимый E2 gate. Лишь затем E3 real FAST.

**Критическое правило:** никакой новый код E2 не должен трактовать `RECORDED` как `VERIFIED_SUCCESS` или `UNKNOWN` как разрешение повторить effect.

## 6. Воспроизведение

```bash
# В отдельном чистом checkout аудиторской ветки
GODOT_BIN="$HOME/.local/opt/godot/Godot_v4.7.2-stable_linux.x86_64"

PYTHONPATH=. python tests/e1_min_independent_live_audit.py \
  --godot "$GODOT_BIN" --evidence-dir /tmp/anima-e1min-evidence

# Повтор замороженного лабораторного E1.2–E1.4 / P5/P6 / M2 baseline
bash scripts/run_e14_live_gate.sh "$GODOT_BIN"
```

Для гарантии полного источника и метрик использовать [аудиторский CI](https://github.com/VankoRokh/ANIMA/actions/runs/45167094963). Система не создаёт пользовательский экземпляр ANIMA; все испытательные данные остаются в изолированных temp и GitHub Actions.
