#!/usr/bin/env python3
"""Opt-in Stage 5 Benchmark v2. Separate corpus/evaluator; v1 is never mutated."""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.workspace_paths import models_root, llama_server_binary

from anima.cognition import CognitivePipeline
from anima.core.event_bus import Event
from anima.diagnostics.trace import DiagnosticTrace
from anima.ir import CanonicalTask, Evidence, HardConstraint, plain
from anima.memory.context_builder import ContextBuilder
from anima.memory.event_log import EventLog
from anima.memory.link_store import LinkStore
from anima.memory.memory_store import MemoryStore
from anima.memory.provenance import ProvenanceResolver
from anima.memory.retrieval import RetrievalEngine
from scripts.run_stage5_smoke import ObservedBackend, ObservedTransport

# Exact inventory/order of the eight-model v1 representative comparison.
MODELS = {
    'Qwen3-0.6B-Q8_0': 'qwen3-0.6b/Qwen3-0.6B-Q8_0.gguf',
    'xLAM-2-1B-fc-r-Q8_0': 'tool-benchmark/xlam-2-1b/xLAM-2-1B-fc-r-Q8_0.gguf',
    'Hammer2.1-0.5B-Q8_0': 'tool-benchmark/hammer2.1-0.5b/hammer2.1-0.5b-Q8_0.gguf',
    'FunctionGemma-270M-Q8_0': 'tool-benchmark/functiongemma-270m/functiongemma-270m-it-q8_0.gguf',
    'Granite-4.0-H-350M-Q8_0': 'tool-benchmark/granite-4.0-h-350m/granite-4.0-h-350m-Q8_0.gguf',
    'Granite-4.0-H-1B-Q8_0': 'tool-benchmark/granite-4.0-h-1b/granite-4.0-h-1b-Q8_0.gguf',
    'Arch-Agent-1.5B-Q8_0': 'tool-benchmark/arch-agent-1.5b/Arch-Agent-1.5B-q8_0.gguf',
    'SmolLM3-3B-Q8_0': 'tool-benchmark/smollm3-3b/SmolLM3-Q8_0.gguf',
}
# v1 explicit generation settings plus the same local server's defaults for
# parameters v1 leaves unspecified. Temperature zero; no per-model overrides.
PARAMETERS = dict(thinking=False, temperature=0.0, top_p=0.8, top_k=40,
                  min_p=0.05, max_output_tokens=256)
POSITIVE = {'projected_text', 'candidate_choice', 'grounded_evidence', 'ambiguous'}


def task(operation, **kwargs):
    return CanonicalTask('v2', 'benchmark-v2', operation, **kwargs)


def corpus():
    action = dict(candidates=('CONTINUE', 'SHUTDOWN'),
                  state={'active_task': True, 'preserve_active_task': True},
                  constraints=(HardConstraint('preserve', 'SHUTDOWN', 'PRESERVE_ACTIVE_TASK'),))
    # Two admissible choices remain; the raw instruction provides the cognitive preference.
    action['candidates'] = ('CONTINUE', 'WAIT', 'SHUTDOWN')
    return [
        ('arithmetic', task('CALCULATE', arguments={'left': Decimal('999999999999.999999'),
            'right': Decimal('999999999999.999998'), 'operator': '-'})),
        ('insufficient', task('QUERY_FACT', subject='pet', predicate='color')),
        ('infeasible', task('CHOOSE_ACTION', candidates=('CHARGE',), state={'charger_available': False},
            constraints=(HardConstraint('charger', 'CHARGE', 'CHARGER_AVAILABLE'),))),
        ('projected_text', task('OPEN', raw_input='Smoke marker: reply exactly COBALT47. No other text.')),
        ('candidate_choice', task('CHOOSE_ACTION', raw_input='Return exactly CONTINUE. Do not explain.', **action)),
        ('invalid_candidate', task('CHOOSE_ACTION', raw_input='Return exactly CONTINUE. Do not explain.', **action)),
        ('grounded_evidence', Event('conversation.user', {'text':
            "What color is the user's bicycle? Answer using the color word from the evidence."},
            source='benchmark-v2', session_id='session_00000002')),
        ('ambiguous', task('QUERY_FACT', subject='pet', predicate='color', output_contract='candidate',
            candidates=('AMBER', 'BLUE'), raw_input='The evidence conflicts. Select either listed color ID.',
            evidence=(Evidence('old', 'AMBER', 'pet', 'color'), Evidence('new', 'BLUE', 'pet', 'color')))),
    ]


def run_scenarios(factory, *, timeout=120.0):
    """One pass through the production pipeline. A factory substitutes only transport."""
    with tempfile.TemporaryDirectory(prefix='anima-stage5-benchmark-v2-') as directory:
        root = Path(directory)
        store = MemoryStore(root/'memory.db')
        links = LinkStore(store)
        log = EventLog(root/'events.jsonl')
        seed = Event('conversation.user', {'text': "The user's bicycle is amber."},
                     source='benchmark-v2', session_id='session_00000001')
        log.write(seed)
        store.create_memory(memory_type='episodic', domain='user', content=seed.payload['text'],
                            status='closed', importance=2, source_event_id=seed.event_id)
        builder = ContextBuilder(retrieval=RetrievalEngine(memory_store=store, link_store=links),
                                 provenance=ProvenanceResolver(store, links, log))
        rows = []
        for name, value in corpus():
            transport = factory()
            injection = 'SHUTDOWN' if name == 'invalid_candidate' else None
            backend = ObservedBackend(transport, timeout, injection)
            trace = DiagnosticTrace()
            pipeline = CognitivePipeline(backend=backend, context_builder=builder, trace=trace)
            started = time.perf_counter()
            turn = None
            error = None
            try:
                turn = pipeline.process_event(value) if isinstance(value, Event) else pipeline.process_task(value)
            except Exception as exception:
                error = {'type': type(exception).__name__, 'message': str(exception)}
            latency = (time.perf_counter()-started)*1000
            audits = [asdict(a) for a in pipeline.backend_audits]
            generations = [c for c in transport.http_calls if c['endpoint'].endswith('/completion')]
            responses = [c['response'] for c in generations if 'response' in c]
            attempts = sum(a['backend_attempts'] for a in audits)
            completions = sum(a['backend_completions'] for a in audits)
            route = next((line.split(' route=')[1].split()[0] for line in (entry['message'] for entry in trace.entries())
                          if line.startswith('resolution:')), None)
            result = turn.final_result if turn else None
            validation_error = turn.error if turn else None
            candidate = None
            if turn and (turn.task.output_contract == 'candidate' or turn.task.operation == 'CHOOSE_ACTION'):
                allowed = turn.resolution.remaining if turn.task.operation == 'CHOOSE_ACTION' else turn.task.candidates
                proposed = turn.fast_turn.result.response_text if turn.fast_turn else result
                candidate = isinstance(proposed, str) and proposed.strip() in (allowed or ())
                if turn.resolution.reason == 'no_admissible_action': candidate = None
            rejection = validation_error == 'invalid_output_candidate'
            expected_route = ('DETERMINISTIC_RESULT' if name in ('arithmetic', 'infeasible') else
                              'INSUFFICIENT_DATA' if name == 'insufficient' else 'COGNITIVE_REQUIRED')
            if name == 'arithmetic': correct = result == Decimal('0.000001')
            elif name == 'insufficient': correct = bool(turn and turn.resolution.missing == ('pet.color',))
            elif name == 'infeasible': correct = bool(turn and turn.resolution.reason == 'no_admissible_action' and result is None)
            elif name == 'projected_text': correct = isinstance(result, str) and 'COBALT47' in result
            elif name == 'grounded_evidence': correct = isinstance(result, str) and re.search(r'\bamber\b', result, re.I) is not None
            elif name == 'candidate_choice': correct = result == 'CONTINUE'
            elif name == 'invalid_candidate': correct = rejection and result is None
            else: correct = result in ('AMBER', 'BLUE')  # Tests routing/validity, not factual adjudication.
            zero = name in ('arithmetic', 'insufficient', 'infeasible')
            count_ok = (attempts, len(generations), completions) == ((0, 0, 0) if zero else (1, 1, 1))
            delivery = zero or bool(transport.prompts and backend.view == json.loads(
                transport.prompts[0]['user_prompt'].split('TASK_VIEW:\n')[1]))
            if generations:
                templates = [c for c in transport.http_calls if c['endpoint'].endswith('/apply-template')]
                delivery = delivery and bool(templates and generations[0]['payload']['prompt'] == templates[0].get('response', {}).get('prompt'))
            raw = responses[0].get('content') if responses else None
            if name == 'projected_text': correct = correct and isinstance(raw, str) and 'COBALT47' in raw
            if name == 'grounded_evidence':
                correct = correct and bool(backend.view and any(
                    e.get('value') == seed.payload['text'] for e in backend.view.get('evidence', [])))
            if name in ('candidate_choice', 'ambiguous'): correct = correct and candidate is True
            def tokens(key):
                if zero: return 0
                values = [r.get(key) for r in responses]
                return sum(values) if values and all(type(n) is int for n in values) else None
            row = dict(scenario=name, route=route, expected_route=expected_route,
                backend_attempts=attempts, generation_requests=len(generations),
                generation_responses=len(responses), successful_completions=completions,
                final_result=plain(result), correctness=bool(correct), candidate_validity=candidate,
                invalid_output_rejection=rejection, latency_ms=latency,
                input_tokens=tokens('tokens_evaluated'), output_tokens=tokens('tokens_predicted'),
                passed=bool(error is None and correct and count_ok and delivery and route == expected_route),
                projection_delivered=delivery, validation_error=validation_error,
                failure_classification=audits[-1]['failure_classification'] if audits else None,
                exception=error, raw_model_response=raw, model_response=backend.model_response,
                backend_response=turn.fast_turn.result.response_text if turn and turn.fast_turn else None,
                fault_injection='replace_result_after_real_completion' if injection else None,
                projected_view=backend.view, rendered_prompts=transport.prompts,
                http_calls=transport.http_calls, backend_audits=audits, trace=trace.entries(),
                resolution={key: plain(getattr(turn.resolution, key)) for key in (
                    'route', 'reason', 'outcome', 'value', 'missing', 'remaining',
                    'unverified', 'rejected', 'derived')} if turn else None,
                context_budget=turn.fast_turn.request.context_bundle.get('budget')
                    if turn and turn.fast_turn and turn.fast_turn.request.context_bundle else None)
            rows.append(row)
    return rows


def summarize(rows):
    attempts = [r['latency_ms'] for r in rows if r['backend_attempts']]
    positives = [r for r in rows if r['scenario'] in POSITIVE]
    return dict(passes=sum(r['passed'] for r in rows), total=len(rows),
        positive_model_passes=sum(r['passed'] for r in positives), positive_model_total=len(positives),
        backend_attempts=sum(r['backend_attempts'] for r in rows),
        generation_requests=sum(r['generation_requests'] for r in rows),
        successful_completions=sum(r['successful_completions'] for r in rows),
        input_tokens=sum(r['input_tokens'] or 0 for r in rows),
        output_tokens=sum(r['output_tokens'] or 0 for r in rows),
        missing_token_rows=sum(r['input_tokens'] is None or r['output_tokens'] is None for r in rows),
        total_latency_ms=sum(r['latency_ms'] for r in rows),
        mean_backend_latency_ms=statistics.mean(attempts) if attempts else None,
        max_backend_latency_ms=max(attempts) if attempts else None)


def get_json(url):
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.load(response)


@contextmanager
def model_server(binary, model, alias, output, port, *, startup_timeout=90):
    """Dedicated port/process; never replace an existing server. No inference retries."""
    url = f'http://127.0.0.1:{port}'
    try:
        get_json(url+'/health')
    except urllib.error.URLError as error:
        if not isinstance(error.reason, ConnectionRefusedError):
            raise RuntimeError('Benchmark port is occupied or unavailable') from error
    else:
        raise RuntimeError('Benchmark port is occupied')
    command = [str(binary), '--model', str(model), '--alias', alias,
        '--host', '127.0.0.1', '--port', str(port), '--device', 'none', '--ctx-size', '4096',
        '--parallel', '1', '--threads', '4', '--threads-batch', '4', '--batch-size', '2048',
        '--ubatch-size', '512', '--cache-type-k', 'f16', '--cache-type-v', 'f16', '--cache-ram', '0',
        '--no-cache-prompt', '--flash-attn', 'auto', '--fit', 'off', '--no-cont-batching',
        '--no-context-shift', '--warmup']
    info = {'base_url': url, 'command': command, 'owned_process_stopped': False}
    with (output/'server.log').open('w') as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        info['pid'] = process.pid
        try:
            deadline = time.monotonic()+startup_timeout
            while True:
                if process.poll() is not None: raise RuntimeError('llama-server exited; see server.log')
                try:
                    if get_json(url+'/health').get('status') == 'ok': break
                except (urllib.error.URLError, urllib.error.HTTPError): pass
                if time.monotonic() >= deadline: raise TimeoutError('Server readiness timeout')
                time.sleep(.1)
            info['models'] = get_json(url+'/v1/models')
            info['properties'] = get_json(url+'/props')
            if alias not in [m['id'] for m in info['models'].get('data', [])]:
                raise RuntimeError('Server identity mismatch')
            path = info['properties'].get('model_path')
            if path and Path(path).resolve() != model.resolve(): raise RuntimeError('Server model path mismatch')
            yield info
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=10)
            info['owned_process_stopped'] = process.poll() is not None


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): digest.update(chunk)
    return digest.hexdigest()


def v1_reference(path):
    if not path.is_file(): return {}
    result = {}
    with path.open(newline='') as stream:
        for row in csv.DictReader(stream):
            if int(row['total_runs']) == 50:
                result[row['model']] = dict(run_id=row['run_id'], passes=int(row['passes']),
                    total=int(row['total_runs']), errors=int(row['errors']),
                    mean_pass_latency_ms=row['mean_pass_latency_ms'] or None)
    return result


def write_summary(output, reports):
    lines = ['# Stage 5 Benchmark v2 — one bounded pass per model', '',
        'PASS includes three model-independent routes and one injected negative case. Positive-model results use four cases only.', '',
        '| Model | PASS / 8 | Positive / 4 | Attempts / generations / completions | Input / output tokens | Mean backend ms | V1 raw PASS / 50 |',
        '|---|---:|---:|---|---|---:|---:|']
    for r in reports:
        s = r.get('summary')
        if not s:
            lines.append(f"| {r['model']} | SETUP ERROR | — | — | — | — | — |")
            continue
        v1 = r.get('v1_reference') or {}
        lines.append(f"| {r['model']} | {s['passes']}/8 | {s['positive_model_passes']}/4 | "
            f"{s['backend_attempts']}/{s['generation_requests']}/{s['successful_completions']} | "
            f"{s['input_tokens']}/{s['output_tokens']} | {s['mean_backend_latency_ms']:.1f} | {v1.get('passes', '—')}/50 |")
    lines += ['', 'V1 function-call quality and V2 scenario scores have different corpora, interfaces and denominators; no accuracy improvement or speedup ratio is implied.',
        'V1 latency is multi-round PASS-only; V2 latency covers every backend attempt, including failed ones. Token totals are observed totals; consult missing_token_rows.',
        'Single observations are descriptive, not a reliability/ranking estimate. See per-model JSON for raw HTTP payloads/responses and fault injection.']
    (output/'comparison.md').write_text('\n'.join(lines)+'\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models-root', type=Path, default=models_root())
    parser.add_argument('--server-binary', type=Path, default=llama_server_binary())
    parser.add_argument('--port', type=int, default=8081)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--output-dir', type=Path, default=ROOT/'.benchmarks/stage5-v2'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0: parser.error('Timeout must be positive and finite')
    if not 1 <= args.port <= 65535: parser.error('Invalid port')
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    fingerprints = {str(p.relative_to(ROOT)): sha256(p) for p in [Path(__file__), ROOT/'scripts/run_stage5_smoke.py',
        ROOT/'anima/ir.py', *sorted((ROOT/'anima/cognition').glob('*.py')), *sorted((ROOT/'anima/resolution').glob('*.py'))]}
    references = v1_reference(ROOT/'.benchmarks/tool-models/comparison.csv')
    reports = []
    version = subprocess.run([str(args.server_binary), '--version'], capture_output=True, text=True, check=True, timeout=10)
    for index, (alias, relative) in enumerate(MODELS.items()):
        directory = output/f'{index+1:02d}'
        directory.mkdir()
        model = args.models_root/relative
        report = dict(benchmark='stage5-benchmark-v2', model=alias, recorded_at=datetime.now(timezone.utc).isoformat(),
            parameters=PARAMETERS, timeout_seconds=args.timeout, repeats=1, runtime_profile='ANIMA FAST CPU v1',
            implementation_sha256=fingerprints, server_binary={'path': str(args.server_binary),
                'sha256': sha256(args.server_binary), 'version': version.stdout+version.stderr},
            v1_reference=references.get(alias))
        print(f'Starting {alias}: {model}', flush=True)
        try:
            if not model.is_file(): raise FileNotFoundError(f'Inventory model unavailable: {model}')
            report['model_file'] = {'path': str(model), 'bytes': model.stat().st_size, 'sha256': sha256(model)}
            with model_server(args.server_binary, model, alias, directory, args.port) as server:
                report['server'] = server
                report['scenarios'] = run_scenarios(lambda: ObservedTransport(
                    base_url=server['base_url'], model=alias, **PARAMETERS), timeout=args.timeout)
                report['summary'] = summarize(report['scenarios'])
        except Exception as error:
            report['setup_error'] = {'type': type(error).__name__, 'message': str(error)}
        (directory/'evidence.json').write_text(json.dumps(plain(report), ensure_ascii=False, indent=2, allow_nan=False)+'\n')
        reports.append(report)
        write_summary(output, reports)
        print(alias, json.dumps(report.get('summary', report.get('setup_error'))), flush=True)
        for row in report.get('scenarios', []):
            print(' ', row['scenario'], 'PASS' if row['passed'] else 'FAIL', repr(row['final_result']),
                  row['failure_classification'], flush=True)
    (output/'comparison.json').write_text(json.dumps(plain(reports), ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(f'Evidence: {output}', flush=True)
    return int(any('setup_error' in r for r in reports))


if __name__ == '__main__':
    raise SystemExit(main())
