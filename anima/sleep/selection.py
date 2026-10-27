from dataclasses import dataclass

from anima.sleep.contracts import COST_HINTS, SourceRef, SourceRegistry, WorkItem
from anima.sleep.store import SleepStore


COST_UNITS = {
    "cheap": 1,
    "normal": 2,
    "expensive": 4,
}


def _validate_non_negative_int(value, label):
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{label} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class SelectionBudget:
    max_items: int
    max_cost_units: int

    def __post_init__(self):
        _validate_non_negative_int(self.max_items, "SelectionBudget max_items")
        _validate_non_negative_int(
            self.max_cost_units,
            "SelectionBudget max_cost_units",
        )


@dataclass(frozen=True, slots=True)
class SelectionCandidate:
    source_ref: SourceRef
    priority: int = 0
    cost_hint: str = "normal"
    eligible: bool = True
    terminal: bool = False

    def __post_init__(self):
        if not isinstance(self.source_ref, SourceRef):
            raise ValueError("SelectionCandidate source_ref must be a SourceRef")
        _validate_non_negative_int(
            self.priority,
            "SelectionCandidate priority",
        )
        if self.cost_hint not in COST_HINTS:
            raise ValueError(
                f"Unknown SelectionCandidate cost_hint: {self.cost_hint!r}"
            )
        if type(self.eligible) is not bool:
            raise ValueError("SelectionCandidate eligible must be bool")
        if type(self.terminal) is not bool:
            raise ValueError("SelectionCandidate terminal must be bool")

    @property
    def cost_units(self):
        return COST_UNITS[self.cost_hint]

    @property
    def source_key(self):
        return (self.source_ref.kind, self.source_ref.source_id)


@dataclass(frozen=True, slots=True)
class SelectionResult:
    work_items: tuple[WorkItem, ...]
    total_cost_units: int
    considered: int
    skipped_ineligible: int
    skipped_terminal: int
    skipped_budget: int
    reused: int


class SleepSelector:
    """Build a deterministic bounded WorkItem queue from source metadata only."""

    def __init__(self, *, sleep_store, source_registry):
        if not isinstance(sleep_store, SleepStore):
            raise ValueError("sleep_store must be a SleepStore")
        if not isinstance(source_registry, SourceRegistry):
            raise ValueError("source_registry must be a SourceRegistry")
        self.sleep_store = sleep_store
        self.source_registry = source_registry

    @staticmethod
    def _normalize_candidates(candidates):
        try:
            values = list(candidates)
        except TypeError as error:
            raise ValueError("candidates must be iterable") from error

        unique = {}
        for candidate in values:
            if not isinstance(candidate, SelectionCandidate):
                raise ValueError(
                    "candidates must contain only SelectionCandidate objects"
                )
            previous = unique.get(candidate.source_key)
            if previous is None:
                unique[candidate.source_key] = candidate
            elif previous != candidate:
                kind, source_id = candidate.source_key
                raise ValueError(
                    "Conflicting selection candidates for source: "
                    f"{kind}:{source_id}"
                )

        return list(unique.values())

    @staticmethod
    def _sort_key(candidate):
        return (
            -candidate.priority,
            candidate.cost_units,
            candidate.source_ref.kind,
            candidate.source_ref.source_id,
        )

    @staticmethod
    def _work_key(work_item):
        return (
            work_item.work_kind,
            work_item.source_ref.kind,
            work_item.source_ref.source_id,
            work_item.processor,
            work_item.processor_version,
        )

    @staticmethod
    def _candidate_work_key(candidate, *, processor, processor_version):
        return (
            "CONSOLIDATE",
            candidate.source_ref.kind,
            candidate.source_ref.source_id,
            processor,
            processor_version,
        )

    def select(
        self,
        *,
        job_id,
        candidates,
        processor,
        processor_version,
        budget,
    ):
        if not isinstance(budget, SelectionBudget):
            raise ValueError("budget must be a SelectionBudget")
        if not isinstance(processor, str) or not processor.strip():
            raise ValueError("processor must be a non-empty string")
        if not isinstance(processor_version, str) or not processor_version.strip():
            raise ValueError("processor_version must be a non-empty string")

        job = self.sleep_store.get_job(job_id)
        if job is None:
            raise ValueError(f"Unknown SleepJob: {job_id}")

        normalized = self._normalize_candidates(candidates)
        skipped_ineligible = sum(not candidate.eligible for candidate in normalized)
        skipped_terminal = sum(
            candidate.eligible and candidate.terminal
            for candidate in normalized
        )
        active = [
            candidate
            for candidate in normalized
            if candidate.eligible and not candidate.terminal
        ]
        ordered = sorted(active, key=self._sort_key)

        existing = {
            self._work_key(work_item): work_item
            for work_item in self.sleep_store.list_work_items(job_id=job_id)
        }

        selected = []
        total_cost_units = 0
        skipped_budget = 0
        reused = 0

        for candidate in ordered:
            if len(selected) >= budget.max_items:
                skipped_budget += 1
                continue

            candidate_cost = candidate.cost_units
            if total_cost_units + candidate_cost > budget.max_cost_units:
                skipped_budget += 1
                continue

            self.source_registry.require(candidate.source_ref)
            key = self._candidate_work_key(
                candidate,
                processor=processor,
                processor_version=processor_version,
            )
            work_item = existing.get(key)

            if work_item is None:
                work_item = WorkItem.create(
                    job_id=job_id,
                    source_ref=candidate.source_ref,
                    processor=processor,
                    processor_version=processor_version,
                    priority=candidate.priority,
                    cost_hint=candidate.cost_hint,
                )
                work_item = self.sleep_store.create_work_item(
                    work_item,
                    source_registry=self.source_registry,
                )
                existing[key] = work_item
            else:
                if (
                    work_item.priority != candidate.priority
                    or work_item.cost_hint != candidate.cost_hint
                ):
                    raise ValueError(
                        "Existing WorkItem metadata conflicts with selection candidate: "
                        f"{candidate.source_ref.kind}:{candidate.source_ref.source_id}"
                    )
                reused += 1

            selected.append(work_item)
            total_cost_units += candidate_cost

        return SelectionResult(
            work_items=tuple(selected),
            total_cost_units=total_cost_units,
            considered=len(normalized),
            skipped_ineligible=skipped_ineligible,
            skipped_terminal=skipped_terminal,
            skipped_budget=skipped_budget,
            reused=reused,
        )
