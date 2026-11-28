# Получение и воспроизведение существующих материалов

Этот документ систематизирует существующие команды; новых критериев и задания аудитору нет. Fresh inference и матрицы при подготовке пакета НЕ запускались.

1. Checkout проверяемого ANIMA snapshot `42d5dbbd6543a952d2aa88f42321f51104038b2f`; последний испытанный implementation `2136b6eed0e6a7d5c776ce018592da1db310717c`.
2. Получить primary materials у владельца из private repository, когда оно будет создано и publication clearance получен. Сейчас проверенных download URLs нет. Не скачивать архивы из публичного ANIMA как будто они опубликованы.
3. Сверить имя/bytes/SHA-256 с EVIDENCE_MANIFEST.json и исходными listings. В локальном full package доступны per-file inventory, exact receipts, original manifests и summaries. Не распаковывать поверх оригиналов; не следовать archive links.
4. Использовать существующую `.venv` и штатный verifier на восстановленных копиях. Original paths в manifests сохранены; перенос требует явной настройки evidence root, не подмены request/response data.

Проверка historical inventory (команда уже есть в проекте; output обязан быть новым каталогом/файлом вне source roots):

```bash
.venv/bin/python -B scripts/audit_e26_r941_evidence.py --evidence-root /home/vanko/ANIMA-Evidence --output /path/to/new/historical-inventory.json
```

Изолированный T-recorded без backend/fresh inference — существующий runner:

```bash
.venv/bin/python -B -m labs.virtual_anima_lab.python.lifecycle.e26_r941_experiments run /home/vanko/ANIMA-Evidence/v0.2/E2.6/R9.4/r941a-0cde809a/plan-control-v2/run-manifest.json --arm T-recorded --output /path/to/new/control-recorded
```

Для Host заменить plan-control-v2 на plan-host-v2 и использовать другой новый output. Подготовка пакета проверяет существующие сохранённые replay receipts; повторный replay здесь не выполнялся. Source scripts должны запускаться из полного ANIMA checkout, а не как автономные извлечённые копии.

Существующие инструкции по H/Q/I/T и offline analysis:

* [R9.4.0](https://github.com/VankoRokh/ANIMA/blob/42d5dbbd6543a952d2aa88f42321f51104038b2f/docs/RESEARCH/e2-6-r940-characterization-v02.md)
* [R9.4.1a](https://github.com/VankoRokh/ANIMA/blob/42d5dbbd6543a952d2aa88f42321f51104038b2f/docs/RESEARCH/e2-6-r941a-observable-v02.md)
* [R9.4.1b](https://github.com/VankoRokh/ANIMA/blob/42d5dbbd6543a952d2aa88f42321f51104038b2f/docs/RESEARCH/e2-6-r941b-baseline-model-experiments-v02.md)
* [R9.4.4](https://github.com/VankoRokh/ANIMA/blob/42d5dbbd6543a952d2aa88f42321f51104038b2f/docs/RESEARCH/e2-6-r944-controlled-evaluation-v02.md)
* [R9.4.5c](https://github.com/VankoRokh/ANIMA/blob/42d5dbbd6543a952d2aa88f42321f51104038b2f/docs/RESEARCH/e2-6-r945c-confirmatory-evaluation-v02.md)

Приведённые в исходных документах команды fresh inference не являются разрешением на повторную матрицу. Отрицательные outcomes, length/terminal rejections, raw IDs и first divergence сохраняются; archived request не подставляется вместо generated request.

GitHub limits: [About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases), отдельный asset меньше2GiB; large archives не помещаются в Git history. Проверять asset bytes и SHA-256 после загрузки независимым download; private authentication и доступ ChatGPT Work проверять отдельно.
