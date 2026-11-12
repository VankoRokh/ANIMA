# ANIMA — E4 Pre-L2 Stage 2: Durable Derived Revision Journal Lab

**Status:** ISOLATED EXPERIMENTAL SQLITE JOURNAL — no production Memory migrations or Core action admission.  
**Implementations:** [revision journal](../../labs/exp009/e4_revision_journal_lab.py), [recovery probe](../../labs/exp009/e4_revision_journal_probe.py).  
**Unit and negative tests:** [transaction/recovery checks](../../tests/test_memory_e4_revision_journal_lab.py), [deterministic raw probe check](../../tests/test_memory_e4_revision_journal_probe.py).

## Intended question

Can source-immutable Events and derived Episode-assignment revisions be durably recorded and recovered **without** overwriting raw Events or repeating a committed revision? This explores storage/transaction properties only. The journal does not decide the semantic validity of an Episode boundary, grant Goal/Task rights, publish Knowledge or trigger an actual external effect.

## Experimental contract

- Entirely separate SQLite file (never opens `memory.db` or `core_state.db`). SQLite WAL and `synchronous=FULL`; each append/revision uses an explicit `BEGIN IMMEDIATE` transaction.
- Raw Event record has stable ID and SHA-256 of canonical JSON. Same ID+identical bytes is idempotent; same ID+changed bytes raises integrity fault.
- Monotonic **source stream revision** increments only for a new Event. A derived revision pins a stream revision and exact source Event ID→digest dependencies.
- Projection head uses **compare-and-swap** on its revision. A correction requires a new user-sourced Event ingested after the original assigned Events; it preserves previous assignment keys and source provenance. This is a **minimal synthetic origin gate, not proof the correction text is actually about those Events**.
- Stable `operation_key` plus request digest prevents replay from creating another revision; a colliding operation key with a different request is an integrity fault.
- Earlier derived versions remain readable. A later source Event makes the snapshot **stale** in the laboratory, even if unrelated; publication preflight refuses stale or non-head versions.
- `publication_guard` returns `lab_preflight_only` and `NO_CORE_PUBLISH_PERMISSION`. It does **not** issue actions or permit real publication.

## Failure injection and limitations

```text
before raw append COMMIT  -> no raw Event, version unchanged
after raw append COMMIT   -> Event persists, replay no-op
before derived COMMIT     -> old head persists, retry may commit
after derived COMMIT      -> new head persists, same operation key replays
source changes afterward -> derived snapshot marked stale / guard denies
same op key, new payload  -> integrity fault
foreign Event / relay correction -> rejected
direct SQLite byte tamper -> detected by stored source/derived digest
```

These tests also expose a deliberate **known semantic admission gap**: the journal accepts a same-user later Event even when its text refers to someone else's tests (X11); correct source scope must be enforced by a separate decision/evidence gate. The raw recovery demo now verifies persisted dependency hashes rather than merely comparing the same in-memory Event dictionaries.

These are **Python-injected exceptions** around transactions, NOT real process kill, lost disk writes, unplugged power, SSD endurance, filesystem errors, cross-database atomicity, concurrent MemoryStore migration or Raspberry Pi validation. The whole-stream dependency epoch is deliberately coarse and may invalidate more derived records than necessary. No measured C3 throughput/latency or retention policy for the growing revision history exists.

## Reproduce

```bash
python -m pytest -q tests/test_memory_e4_revision_journal_lab.py tests/test_memory_e4_revision_journal_probe.py
python -m labs.exp009.e4_revision_journal_probe --output /tmp/e4-recovery-lab.json
```

**Acceptance criterion for this stage:** tests + raw probe demonstrate atomicity in the isolated journal and distinguish stale/read-only from authorized publication; they do not certify a production E4 memory engine. To progress, design a bridge to actual Event identity/provenance with snapshot/recovery authority, selective dependency invalidation and real kill/power-loss testing.
