# ANIMA FAST CPU v1

## Назначение

`ANIMA FAST CPU v1` — фиксированный runtime-профиль `llama-server` для
сравнительных прогонов [ANIMA Tool Model Benchmark v1](Tool_Model_Benchmark.md).
Он нужен, чтобы различия latency и RAM отражали различия моделей, а не скрытые
изменения контекста, числа server slots, offload или cache policy.

Результаты разных моделей считаются напрямую сопоставимыми только если они
получены на одном runtime-профиле и одном benchmark corpus/evaluator snapshot.
Если профиль необходимо изменить, создаётся новая версия профиля и предыдущие
результаты не смешиваются с новой серией без повторного baseline.

## Зафиксированная среда v1

Для серии `ANIMA FAST CPU v1` зафиксирован backend:

```text
llama.cpp: 0.7.0-dev
build:     11943
commit:    a91917994
compiler:  GNU 15.2.0
platform:  Linux x86_64
```

Benchmark-машина использует 4 физических CPU-ядра. Для профиля v1 inference
выполняется только на CPU; GPU/offload не используются.

Обновление `llama.cpp`, смена benchmark-машины или изменение числа доступных
физических ядер требует либо повторного прогона всех сравниваемых моделей, либо
новой версии runtime-профиля.

## Фиксированные параметры `llama-server`

| Параметр | Значение v1 | Причина |
|---|---:|---|
| Device | `none` | CPU-only baseline без GPU offload |
| Context | `4096` | достаточно для benchmark и не зависит от native context модели |
| Parallel slots | `1` | один агент, без multi-user server overhead |
| Generation threads | `4` | число физических CPU-ядер benchmark-машины |
| Batch threads | `4` | то же фиксированное CPU-условие |
| Logical batch | `2048` | фиксированное условие prompt processing |
| Physical ubatch | `512` | фиксированное условие prompt processing |
| KV cache K | `f16` | единый cache format |
| KV cache V | `f16` | единый cache format |
| Host cache RAM | `0` | отключить дополнительный host cache |
| Prompt cache | `off` | исключить влияние предыдущих benchmark-сценариев |
| Flash Attention | `auto` | одинаковая политика backend для всех моделей |
| Fit/autotuning | `off` | сервер не меняет параметры под конкретную модель |
| Continuous batching | `off` | один последовательный benchmark workload |
| Context shift | `off` | benchmark не использует бесконечное продолжение контекста |
| Warmup | `on` | measured run не включает cold initialization |
| Host | `127.0.0.1` | локальный backend |
| Port | `8080` | стандартный endpoint benchmark-серии |

Каноническая команда запуска:

```bash
cd ~/Projects/llama.cpp

MODEL=/path/to/model.gguf
ALIAS=model-benchmark-alias

./build/bin/llama-server \
  --model "$MODEL" \
  --alias "$ALIAS" \
  --host 127.0.0.1 \
  --port 8080 \
  --device none \
  --ctx-size 4096 \
  --parallel 1 \
  --threads 4 \
  --threads-batch 4 \
  --batch-size 2048 \
  --ubatch-size 512 \
  --cache-type-k f16 \
  --cache-type-v f16 \
  --cache-ram 0 \
  --no-cache-prompt \
  --flash-attn auto \
  --fit off \
  --no-cont-batching \
  --no-context-shift \
  --warmup
```

После запуска профиль проверяется минимум командами:

```bash
curl -s http://127.0.0.1:8080/v1/models
pgrep -a llama-server
PID="$(pgrep -n llama-server)"
grep -E 'VmRSS|VmHWM' /proc/$PID/status
```

`/v1/models` должен показывать `n_ctx=4096`, а строка процесса — полный набор
зафиксированных аргументов.

## Фиксированные параметры benchmark runner

Серверный профиль дополняется одинаковыми параметрами benchmark runner:

```text
temperature = 0
max_tokens  = 256
repeats     = 1 для smoke, затем 5 для representative baseline
thinking    = off, если adapter/model позволяет это контролировать
```

Для representative performance run PID сервера передаётся явно через
`--server-pid`; auto-detection не используется как предпочтительный путь.

## Что разрешено менять между моделями

Между кандидатами разрешено менять только параметры, описывающие саму модель или
необходимый для неё protocol adapter:

- путь к GGUF/model file;
- API alias;
- заявленное число параметров;
- quantization;
- model-specific chat/function-calling template;
- adapter, если native protocol модели требует другой интеграции.

Model-specific template/adapter не считается нарушением профиля: benchmark
сравнивает способность модели работать через её корректный поддерживаемый
function-calling protocol, а не способность понимать чужой template.

Нельзя молча менять ради отдельной модели:

- `ctx-size`;
- CPU/GPU mode;
- число threads/slots;
- batch/ubatch;
- KV cache types;
- prompt/cache policy;
- continuous batching;
- context shift;
- warmup/fit policy.

Если кандидат не может корректно работать в этих условиях, это фиксируется как
ограничение/несовместимость. Альтернативный набор условий получает отдельное имя
профиля, например будущий `ANIMA FAST GPU v1`, и его результаты не смешиваются с
`ANIMA FAST CPU v1`.

## Evidence и воспроизводимость

Для каждого representative baseline необходимо сохранить или указать:

- runtime profile: `ANIMA FAST CPU v1`;
- commit benchmark-кода;
- `llama.cpp` version/build/commit;
- model name и точный model file;
- parameters/quantization;
- server PID и фактическую команду запуска;
- `n_ctx`, возвращённый `/v1/models`;
- smoke/baseline repeats;
- benchmark runner arguments;
- RSS before, sampled max RSS, VmHWM и доступные VRAM measurements.

Изменение одного из фиксированных условий делает результат отдельной серией, а
не продолжением существующей comparison table.

## Контрольная проверка профиля на Qwen3-0.6B

При переходе от неограниченного model-native context (`40960`) и auto server
slots к `ANIMA FAST CPU v1` (`ctx=4096`, `parallel=1`, CPU-only) для
`Qwen3-0.6B-Q8_0` наблюдалось снижение `llama-server` RSS примерно с 5.15 GiB до
1.12 GiB до benchmark; sampled max в стандартизированном smoke был около 1.15 GiB.

Эти числа являются диагностической проверкой того, что профиль реально изменил
runtime footprint, а не нормативом для модели. Официальное сравнение использует
сохранённые результаты representative baseline, а не эти ориентировочные значения.

## Известные ограничения профиля

- RSS/VRAM в benchmark остаются sampled measurements и могут пропустить короткий пик;
- `VmHWM` относится ко всей жизни процесса `llama-server`;
- CPU-only профиль не измеряет выгоду от CUDA/GPU offload;
- результаты привязаны к указанному build `llama.cpp` и benchmark-машине;
- производительность CM5/Raspberry Pi не выводится напрямую из laptop CPU baseline.

Профиль v1 предназначен прежде всего для честного относительного сравнения
кандидатов FAST/action layer на одной и той же локальной машине.