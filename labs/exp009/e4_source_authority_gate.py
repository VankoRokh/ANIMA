"""E4 isolated mock source-admission/ownership gate.

This is NOT a production authentication mechanism. A trusted test fixture holds
adapter tokens outside Event payloads. Unauthorized raw Events can be stored as
evidence but may not change alias heads through this guarded class.
"""
from dataclasses import dataclass, field
import hmac
from pathlib import Path
from types import MappingProxyType

from anima.core.event_bus import Event
from labs.exp009.e4_alias_lifecycle_lab import (
    AliasLifecycleLab, LifecycleConflict, LifecycleIntegrity, _digest, _json,
    _receipt,
)

POLICY_REVISION = 1


class AuthorityDenied(LifecycleConflict):
    """Denied by an isolated synthetic source-authority gate."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class LabAdapterRegistration:
    adapter_ref: str
    principal_id: str
    token: bytes = field(repr=False)

    def __post_init__(self):
        if (not isinstance(self.adapter_ref, str)
                or not self.adapter_ref.strip()
                or not isinstance(self.principal_id, str)
                or not self.principal_id.strip()
                or type(self.token) is not bytes
                or len(self.token) < 16):
            raise ValueError("Malformed lab adapter registration")


class AuthorizedAliasLifecycleLab(AliasLifecycleLab):
    """Fail-closed alias lifecycle on *admitted* Events, in the same SQLite DB.

    The boundary before admit_event() is assumed trusted. A caller in control of
    that boundary or process can forge authority; no real identity is proved.
    """

    def __init__(self, path, *, adapters):
        if not isinstance(adapters, dict) or not adapters:
            raise ValueError("Explicit trusted lab adapter registry required")
        registry = dict(adapters)
        if any(not isinstance(v, LabAdapterRegistration) or k != v.adapter_ref
               for k, v in registry.items()):
            raise ValueError("Lab adapter registry mismatch")
        self._adapters = MappingProxyType(registry)
        super().__init__(path)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS trusted_admissions(
                    event_id TEXT PRIMARY KEY,
                    source_sha256 TEXT NOT NULL,
                    principal_id TEXT NOT NULL,
                    adapter_ref TEXT NOT NULL,
                    policy_revision INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alias_owners(
                    alias_id TEXT PRIMARY KEY,
                    definition_event_id TEXT NOT NULL UNIQUE,
                    source_sha256 TEXT NOT NULL,
                    owner_principal_id TEXT NOT NULL,
                    admission_adapter_ref TEXT NOT NULL,
                    policy_revision INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS allowed_revocations(
                    operation_key TEXT PRIMARY KEY,
                    alias_id TEXT NOT NULL,
                    from_revision INTEGER NOT NULL,
                    definition_event_id TEXT NOT NULL,
                    revocation_event_id TEXT NOT NULL,
                    revocation_sha256 TEXT NOT NULL,
                    admitted_principal_id TEXT NOT NULL,
                    policy_revision INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS denied_authority(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_key TEXT NOT NULL,
                    action TEXT NOT NULL,
                    alias_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
            """)

    def admit_event(self, raw, *, adapter_ref, token):
        """Trust-boundary simulation: token is NOT taken from the raw Event."""
        if type(token) is not bytes:
            raise AuthorityDenied("BAD_ADAPTER_TOKEN")
        reg = self._adapters.get(adapter_ref) if isinstance(adapter_ref, str) else None
        if reg is None:
            raise AuthorityDenied("UNKNOWN_ADAPTER")
        if not hmac.compare_digest(reg.token, token):
            raise AuthorityDenied("BAD_ADAPTER_TOKEN")
        Event.validate_record(raw)
        body = _json(raw)
        digest = _digest(body)
        with self._tx() as db:
            row = db.execute(
                "SELECT body,digest,seq FROM raw_events WHERE event_id=?",
                (raw["id"],),
            ).fetchone()
            if row:
                if row["body"] != body or row["digest"] != digest:
                    raise LifecycleIntegrity("Event ID collision during trusted admission")
                seq = row["seq"]
            else:
                seq = db.execute(
                    "SELECT COALESCE(MAX(seq),0)+1 FROM raw_events"
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO raw_events VALUES(?,?,?,?)",
                    (raw["id"], seq, body, digest),
                )
            prior = db.execute(
                "SELECT * FROM trusted_admissions WHERE event_id=?",
                (raw["id"],),
            ).fetchone()
            if prior:
                if (prior["principal_id"] != reg.principal_id
                        or prior["adapter_ref"] != reg.adapter_ref
                        or prior["source_sha256"] != digest
                        or prior["policy_revision"] != POLICY_REVISION):
                    raise LifecycleConflict("Admitted Event owner cannot be rebound")
                status = "idempotent_replay"
            else:
                db.execute(
                    "INSERT INTO trusted_admissions VALUES(?,?,?,?,?)",
                    (raw["id"], digest, reg.principal_id,
                     reg.adapter_ref, POLICY_REVISION),
                )
                status = "admitted"
        return _receipt(
            "Admission", status=status, event_id=raw["id"], seq=seq,
            principal_id=reg.principal_id, policy_revision=POLICY_REVISION,
            trusted_boundary="SYNTHETIC_ADAPTER_FIXTURE_ONLY",
            real_identity_verified=False,
        )

    @staticmethod
    def _admission(db, event_id, expected_digest, reason):
        row = db.execute(
            "SELECT * FROM trusted_admissions WHERE event_id=?", (event_id,),
        ).fetchone()
        if row is None:
            raise AuthorityDenied(reason)
        if row["source_sha256"] != expected_digest:
            raise LifecycleIntegrity("Trusted admission source digest mismatch")
        if row["policy_revision"] != POLICY_REVISION:
            raise AuthorityDenied("OUTDATED_AUTHORITY_POLICY")
        return row

    def _authorize_definition_tx(self, db, alias_id, definition_event_id,
                                 definition_digest, operation_key):
        admission = self._admission(
            db, definition_event_id, definition_digest, "UNADMITTED_DEFINITION")
        db.execute(
            "INSERT INTO alias_owners VALUES(?,?,?,?,?,?)",
            (alias_id, definition_event_id, definition_digest,
             admission["principal_id"], admission["adapter_ref"],
             POLICY_REVISION),
        )

    def _authorize_revocation_tx(self, db, alias_id, definition_event_id,
                                 revocation_event_id, revocation_digest,
                                 expected_head, operation_key):
        owner = db.execute(
            "SELECT * FROM alias_owners WHERE alias_id=?", (alias_id,),
        ).fetchone()
        if owner is None:
            raise AuthorityDenied("UNOWNED_ALIAS")
        if owner["definition_event_id"] != definition_event_id:
            raise LifecycleIntegrity("Alias owner definition mismatch")
        if owner["policy_revision"] != POLICY_REVISION:
            raise AuthorityDenied("OUTDATED_AUTHORITY_POLICY")
        _raw_definition, definition_digest, _seq = self._raw(
            db, definition_event_id)
        if definition_digest != owner["source_sha256"]:
            raise LifecycleIntegrity("Alias owner source digest mismatch")
        revocation = self._admission(
            db, revocation_event_id, revocation_digest, "UNADMITTED_REVOCATION")
        if revocation["principal_id"] != owner["owner_principal_id"]:
            raise AuthorityDenied("FOREIGN_OWNER")
        db.execute(
            "INSERT INTO allowed_revocations VALUES(?,?,?,?,?,?,?,?)",
            (operation_key, alias_id, expected_head, definition_event_id,
             revocation_event_id, revocation_digest, revocation["principal_id"],
             POLICY_REVISION),
        )

    def _audit_denial(self, action, alias_id, event_id, operation_key, reason):
        # Separate durable audit after a denial transaction rolled back. A log
        # entry is not a permission and must never mutate the alias head.
        with self._tx() as db:
            db.execute(
                "INSERT INTO denied_authority(operation_key,action,alias_id,"
                "event_id,reason) VALUES(?,?,?,?,?)",
                (operation_key, action, alias_id, event_id, reason),
            )

    def define(self, *, alias_id, definition_event_id, operation_key,
               expected_head=0, cut=None):
        try:
            return super().define(
                alias_id=alias_id, definition_event_id=definition_event_id,
                operation_key=operation_key, expected_head=expected_head,
                cut=cut)
        except AuthorityDenied as exc:
            self._audit_denial(
                "define", alias_id, definition_event_id, operation_key,
                exc.reason)
            raise

    def revoke(self, *, alias_id, revocation_event_id, expected_head,
               operation_key, cut=None):
        try:
            return super().revoke(
                alias_id=alias_id, revocation_event_id=revocation_event_id,
                expected_head=expected_head, operation_key=operation_key,
                cut=cut)
        except AuthorityDenied as exc:
            self._audit_denial(
                "revoke", alias_id, revocation_event_id, operation_key,
                exc.reason)
            raise

    def owner(self, alias_id):
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM alias_owners WHERE alias_id=?", (alias_id,)
            ).fetchone()
            return None if row is None else dict(row)

    def allowed_decision(self, operation_key):
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM allowed_revocations WHERE operation_key=?",
                (operation_key,),
            ).fetchone()
            return None if row is None else dict(row)

    def denial_reasons(self):
        with self._connection() as db:
            return [row["reason"] for row in db.execute(
                "SELECT reason FROM denied_authority ORDER BY id")]

    def authority_counts(self):
        with self._connection() as db:
            return {
                table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "trusted_admissions", "alias_owners",
                    "allowed_revocations", "denied_authority",
                )
            }
