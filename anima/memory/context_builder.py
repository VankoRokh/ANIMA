import json


CONSUMER_POLICIES = {
    "FAST": {
        "default_max_items": 6,
        "default_max_chars": 1200,
        "retrieval_top_k": 12,
        "relation_hops": 0,
        "include_events": False,
    },
    "DEEP": {
        "default_max_items": 16,
        "default_max_chars": 4000,
        "retrieval_top_k": 32,
        "relation_hops": 1,
        "include_events": True,
    },
}

MAX_CONTEXT_ITEMS = 100
MAX_CONTEXT_CHARS = 100_000


class ContextBuilder:
    """Build a deterministic, budgeted Stage 1.9 working ContextBundle."""

    def __init__(self, *, retrieval, provenance, trace=None):
        self.retrieval = retrieval
        self.provenance = provenance
        self.trace = trace

    def build(
        self,
        query,
        *,
        consumer="FAST",
        max_items=None,
        max_chars=None,
        retrieval_options=None,
    ):
        consumer = self._validate_consumer(consumer)
        policy = CONSUMER_POLICIES[consumer]
        max_items = self._validate_budget(
            max_items,
            policy["default_max_items"],
            MAX_CONTEXT_ITEMS,
            "max_items",
        )
        max_chars = self._validate_budget(
            max_chars,
            policy["default_max_chars"],
            MAX_CONTEXT_CHARS,
            "max_chars",
        )
        retrieval_options = self._validate_retrieval_options(
            retrieval_options
        )

        seed_top_k = min(
            100,
            max(policy["retrieval_top_k"], max_items * 2),
        )
        retrieval_response = self.retrieval.retrieve(
            query,
            top_k=seed_top_k,
            relation_hops=policy["relation_hops"],
            **retrieval_options,
        )

        candidates = retrieval_response["results"]
        knowledge_candidates = [
            item for item in candidates if item["kind"] == "knowledge"
        ]
        memory_candidates = [
            item for item in candidates if item["kind"] == "memory"
        ]

        bundle = {
            "query": query,
            "consumer": consumer,
            "budget": {
                "max_items": max_items,
                "max_chars": max_chars,
            },
            "knowledge": [],
            "memories": [],
            "events": [],
            "truncated": False,
            "selection_stats": {
                "retrieval_candidates": retrieval_response["stats"][
                    "candidates"
                ],
                "retrieval_returned": retrieval_response["stats"][
                    "returned"
                ],
                "knowledge_considered": len(knowledge_candidates),
                "memories_considered": len(memory_candidates),
                "events_considered": 0,
                "selected_knowledge": 0,
                "selected_memories": 0,
                "selected_events": 0,
                "items_used": 0,
                "chars_used": 0,
                "omitted_budget": 0,
            },
        }

        if retrieval_response["stats"]["candidates"] > len(candidates):
            bundle["truncated"] = True

        for candidate in self._selection_order(candidates):
            kind = candidate["kind"]
            bucket = "knowledge" if kind == "knowledge" else "memories"
            entry = self._context_entry(candidate)
            if self._try_add(
                bundle,
                bucket,
                entry,
                self._record_text(kind, candidate["record"]),
            ):
                if kind == "knowledge":
                    bundle["selection_stats"]["selected_knowledge"] += 1
                else:
                    bundle["selection_stats"]["selected_memories"] += 1

        if policy["include_events"]:
            event_candidates = self._events_for_selected(bundle)
            bundle["selection_stats"]["events_considered"] = len(
                event_candidates
            )
            for event_entry in event_candidates:
                if self._try_add(
                    bundle,
                    "events",
                    event_entry,
                    self._event_text(event_entry["record"]),
                ):
                    bundle["selection_stats"]["selected_events"] += 1

        self._trace_bundle(bundle)
        return bundle

    @staticmethod
    def _validate_consumer(consumer):
        if not isinstance(consumer, str) or not consumer.strip():
            raise ValueError("Context consumer must be FAST or DEEP")
        consumer = consumer.strip().upper()
        if consumer not in CONSUMER_POLICIES:
            raise ValueError("Context consumer must be FAST or DEEP")
        return consumer

    @staticmethod
    def _validate_budget(value, default, maximum, label):
        if value is None:
            return default
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= maximum
        ):
            raise ValueError(
                f"Context {label} must be an integer from 1 to {maximum}"
            )
        return value

    @staticmethod
    def _validate_retrieval_options(options):
        if options is None:
            return {}
        if not isinstance(options, dict):
            raise ValueError("Context retrieval_options must be a dict")
        forbidden = {"query", "top_k", "relation_hops"} & set(options)
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise ValueError(
                "Context Builder owns retrieval policy fields: " + names
            )
        return dict(options)

    @staticmethod
    def _selection_order(candidates):
        exact = [
            item
            for item in candidates
            if "exact_id:+100" in item["reasons"]
        ]
        exact_keys = {(item["kind"], item["id"]) for item in exact}
        knowledge = [
            item
            for item in candidates
            if item["kind"] == "knowledge"
            and (item["kind"], item["id"]) not in exact_keys
        ]
        memories = [
            item
            for item in candidates
            if item["kind"] == "memory"
            and (item["kind"], item["id"]) not in exact_keys
        ]
        return exact + knowledge + memories

    @staticmethod
    def _context_entry(candidate):
        return {
            "record": candidate["record"],
            "score": candidate["score"],
            "selection_reason": list(candidate["reasons"]),
        }

    @staticmethod
    def _record_text(kind, record):
        if kind == "knowledge":
            return record["statement"]
        return record["content"]

    @staticmethod
    def _event_text(event):
        payload = event.get("payload")
        if isinstance(payload, dict):
            text = payload.get("text")
            if isinstance(text, str):
                return text
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _event_entry(event, reasons):
        return {
            "record": event,
            "selection_reason": sorted(reasons),
        }

    def _events_for_selected(self, bundle):
        event_map = {}

        for entry in bundle["knowledge"]:
            knowledge_id = entry["record"]["id"]
            resolved = self.provenance.knowledge(knowledge_id)
            for source in resolved["sources"]:
                for event in source["events"]:
                    key = event["id"]
                    item = event_map.setdefault(
                        key,
                        {
                            "record": event,
                            "reasons": set(),
                        },
                    )
                    item["reasons"].add(
                        f"provenance:knowledge:{knowledge_id}"
                    )

        for entry in bundle["memories"]:
            memory_id = entry["record"]["id"]
            resolved = self.provenance.memory(memory_id)
            for event in resolved["events"]:
                key = event["id"]
                item = event_map.setdefault(
                    key,
                    {
                        "record": event,
                        "reasons": set(),
                    },
                )
                item["reasons"].add(
                    f"provenance:memory:{memory_id}"
                )

        ordered = sorted(
            event_map.values(),
            key=lambda item: (
                item["record"]["timestamp"],
                item["record"]["id"],
            ),
        )
        return [
            self._event_entry(item["record"], item["reasons"])
            for item in ordered
        ]

    @staticmethod
    def _fits(bundle, char_cost):
        stats = bundle["selection_stats"]
        budget = bundle["budget"]
        if stats["items_used"] + 1 > budget["max_items"]:
            return False
        if stats["chars_used"] + char_cost > budget["max_chars"]:
            return False
        return True

    def _try_add(self, bundle, bucket, entry, text):
        char_cost = len(text)
        if not self._fits(bundle, char_cost):
            bundle["truncated"] = True
            bundle["selection_stats"]["omitted_budget"] += 1
            return False

        bundle[bucket].append(entry)
        bundle["selection_stats"]["items_used"] += 1
        bundle["selection_stats"]["chars_used"] += char_cost
        return True

    def _trace_bundle(self, bundle):
        if self.trace is None:
            return
        stats = bundle["selection_stats"]
        self.trace.record(
            "context_builder: "
            f"consumer={bundle['consumer']} "
            f"items={stats['items_used']}/{bundle['budget']['max_items']} "
            f"chars={stats['chars_used']}/{bundle['budget']['max_chars']} "
            f"knowledge={stats['selected_knowledge']} "
            f"memories={stats['selected_memories']} "
            f"events={stats['selected_events']} "
            f"truncated={str(bundle['truncated']).lower()}"
        )
