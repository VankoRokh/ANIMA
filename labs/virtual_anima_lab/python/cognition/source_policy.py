"""Shared deterministic source policy for the read-only laboratory turn.

No memory stores, service dispatch, model transport or execution authority.
"""
from __future__ import annotations

import re


class E25CognitionError(RuntimeError):
    pass


class TurnSourcePolicy:
    """Host-owned exposed event/sample bindings; never populated from a proposal.

    The full frozen Context is supplied to adapters. Only its typed source
    references and completed trusted service results can extend this set.
    Memory OFF permits only the latest captured sample, not all known IDs.
    """

    def __init__(self, context):
        self._latest = context["latest_sample_id"]
        self._memory_enabled = context["memory_enabled"]
        self._source = context["source_ref"]
        self._prefix = f'worldobs:{context["world_instance_id"]}:{context["epoch"]}:'
        self._exposed = {}
        self.expose_entities(context["entities"])
        for row in context["relations"]:
            self._expose(row["last_event_id"], row["last_sample_id"])
        for row in context["observed_revisions"]:
            self._expose(row["previous_event_id"], row["previous_sample"])
            self._expose(row["current_event_id"], row["current_sample"])

    def _sequence(self, sample):
        if type(sample) is not str or not sample.startswith(self._prefix):
            raise E25CognitionError("SOURCE_OUTSIDE_FROZEN_SCOPE")
        suffix = sample[len(self._prefix):]
        if re.fullmatch(r"[1-9][0-9]*", suffix) is None:
            raise E25CognitionError("SOURCE_OUTSIDE_FROZEN_SCOPE")
        return int(suffix)

    def _check_scope(self, sample):
        if (self._sequence(sample) > self._sequence(self._latest)
                or (not self._memory_enabled and sample != self._latest)):
            raise E25CognitionError("SOURCE_OUTSIDE_FROZEN_SCOPE")

    def _expose(self, event, sample):
        self._check_scope(sample)
        if (type(event) is not str or not event
                or self._exposed.get(event, sample) != sample):
            raise E25CognitionError("SOURCE_IDENTITY_MISMATCH")
        self._exposed[event] = sample

    def expose_entities(self, rows):
        for row in rows:
            self._expose(row["last_seen_event_id"], row["last_seen_sample"])

    def exposed_bindings(self):
        """Return a detached snapshot, never a mutable authority handle."""
        return dict(self._exposed)

    def permits(self, event_ids):
        return all(event in self._exposed for event in event_ids)

    def check_result(self, kind, args, result):
        if kind == "retrieve_memory":
            # Validate in a temporary mapping. Commit exposures only after the
            # outcome is size-checked, freshness-checked and journaled.
            pending = dict(self._exposed)
            for row in result["records"]:
                event, sample = row["last_seen_event_id"], row["last_seen_sample"]
                self._check_scope(sample)
                if (type(event) is not str or not event
                        or pending.get(event, sample) != sample):
                    raise E25CognitionError("SOURCE_IDENTITY_MISMATCH")
                pending[event] = sample
        elif kind in ("lookup_raw_evidence", "inspect_latest_observation"):
            rows = result["records"]
            expected = args.get("event_ids", [])
            if kind == "lookup_raw_evidence":
                if [row["event_id"] for row in rows] != expected:
                    raise E25CognitionError("SOURCE_IDENTITY_MISMATCH")
            elif len(rows) != 1:
                raise E25CognitionError("SOURCE_IDENTITY_MISMATCH")
            for row in rows:
                if row["status"] != "verified_source_view":
                    raise E25CognitionError("SOURCE_NOT_VERIFIED")
                sample = row["sample_id"]
                self._check_scope(sample)
                event = row["event_id"]
                if (type(event) is not str or not event
                        or self._exposed.get(event, sample) != sample
                        or row["source_ref"] != self._source
                        or type(row["sample_seq"]) is not int
                        or row["sample_seq"] != self._sequence(sample)
                        or (kind == "inspect_latest_observation" and sample != self._latest)
                        or (kind == "lookup_raw_evidence"
                            and self._exposed.get(row["event_id"]) != sample)):
                    raise E25CognitionError("SOURCE_IDENTITY_MISMATCH")
        elif kind == "inspect_current_belief" and not self._memory_enabled:
            # Legacy belief reads are not an alternative route to historical
            # evidence IDs. Belief does not grant additional Raw authority.
            if any(self._exposed.get(event) != self._latest
                   for event in result["record"]["evidence_event_ids"]):
                raise E25CognitionError("SOURCE_OUTSIDE_FROZEN_SCOPE")

    def record_completed(self, kind, result):
        if kind == "retrieve_memory":
            self.expose_entities(result["records"])
        elif kind == "inspect_latest_observation":
            row = result["records"][0]
            self._expose(row["event_id"], row["sample_id"])


__all__ = ["E25CognitionError", "TurnSourcePolicy"]
