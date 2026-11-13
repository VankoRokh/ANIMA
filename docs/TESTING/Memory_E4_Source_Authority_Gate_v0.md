# ANIMA E4 — Isolated Source Authority Gate v0

**Status:** PREDECLARED TEST CONTRACT / NOT PRODUCTION ADMISSION. Baseline `e422c5255cefa56b8519c660fe6f797371736d31`, research branch `experiment/core-memory-information-baseline`. The previous [post-alias negative result](Memory_E4_PostAlias_Authority_Graph_Gate_v0.md) is a real blocker: user-controlled `source="user"` was sufficient to revoke.

## Question

Can an isolated laboratory enforce an **independently admitted principal** on both an alias definition and its revocation, while atomically preserving the existing selective invalidation, raw history, operation replay and after-crash recovery? This tests a boundary assumption, **not** actual identity authentication.

## Authority model (fixed before implementation)

- `Event.source`, `session_id`, Event refs, text, payload `alias_control` and SHA-256 prove *neither* identity nor permission.
- Only an external **trusted test adapter registration** maps an adapter credential to a `principal_id`. This registration is supplied by the trusted lab fixture, not accepted from the Event. This is a synthetic mock of a security boundary, not a credential manager or real-world user authentication.
- Atomic admission binds a validated raw Event ID and its immutable SHA-256 digest to a principal and fixed policy revision in the *same isolated SQLite database*. An unbound raw Event may remain as evidence, but it cannot define or revoke an active alias. A second principal cannot take over an admitted Event ID.
- Defining an alias atomically records `alias_id → owner_principal / definition_event_id / admission_digest`. Refusing to define cannot leave behind a half-owned alias.
- Revocation must cite exactly that definition, be later than it, match existing source-shape rules **and** carry a trusted admission for the **same principal**. Different sessions are allowed for the same admitted principal. Unknown, missing, wrong credential, different principal, duplicate source ID with changed bytes, forged `source="user"`, and unsigned relay are denied.
- The decision is made **inside the same SQLite transaction** as changing the alias head and marking graph descendants stale, not in a preflight followed by a separate unprotected write. A durable allowed-decision receipt records principal, policy revision, alias/version, exact admitted revocation Event, operation key and cause source digest.
- Denials leave aliases, dependency heads, invalidation ledger and previously committed operation records **unchanged**. A separate lab-only denial audit is permitted; it must not authorize any retry.
- Existing base `AliasLifecycleLab` remains a deliberately vulnerable **lab-only historical baseline**. New gate tests MUST instantiate the *authority-guarded subclass*, which enforces the authorization hook even when the ordinary `define()` / `revoke()` methods are invoked directly. This is not a production bridge.
- No override, delegation, ownership transfer, automatic retarget, LLM role, SLEEP, Core-managed permissions, physical identity assurance, action execution, or production Memory writes.

## Predeclared acceptance tests

| Scenario | Expected observation |
| --- | --- |
| Alice defines A using admitted Event; same Alice revokes A in later session | Only A descendants stale; B remains active; auditable decision same DB transaction |
| Mallory submits fully valid raw `source="user"` revocation, no admitted identity | FAIL CLOSED; A and dependents unchanged; denial audit |
| Mallory admitted through different test credential but references Alice's A | FAIL CLOSED, even if timestamp/source/ref match |
| Invalid credential / unknown adapter | No raw admission; no privilege |
| Same Event ID admitted by different principal, or replay with changed bytes | Conflict, no silent owner change |
| Defining alias without admitted source | FAIL CLOSED, no orphan alias owner |
| Same principal cross-session, exact source ref | Allowed |
| Operation replay after reopen | No duplicate version/invalidation/decision; original evidence intact |
| Before-commit injected fault | Whole authority decision + alias/invalidation rollback |
| After-commit injected fault | Entire authorized effect survives reopen |
| >128 invalidated descendants | Whole authorized operation rolls back, including its authority receipt. **Still an open correction-availability risk**. |
| Existing E4 adversarial suite and independent graph oracle | No regressions; production unchanged |

## Security limits

The trusted test adapter token is a **lab fixture**; possession is not proof of a specific human or cryptographic transport authentication. Python object privacy and process-local secrets are not a security perimeter if arbitrary code can run inside the trusted process. The adapter is assumed to authenticate the upstream caller *before* invoking the lab; that assumption remains untested. Direct SQLite edits, stolen test tokens, file-system compromise, replay across separately cloned DBs, multi-DB transactions and real process kill are excluded.

**Verdict policy:** A green test is **LAB AUTHORITY BINDING PASS** only, not identity verification, Core authority, production memory admission or L2 GO. An unbound or foreign principal changing any alias head is an unconditional FAIL.
