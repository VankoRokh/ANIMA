from dataclasses import dataclass

from anima.sleep.execution import ExecutionOutcome, SleepChunkExecutor
from anima.sleep.recovery import SleepRecoveryCoordinator
from anima.sleep.store import SleepStore


TERMINAL_JOB_STATUSES = {"completed", "failed"}


@dataclass(frozen=True, slots=True)
class SleepRuntimeStatus:
    active_job_id: str | None
    job_status: str | None
    work_items: tuple[dict, ...]

    def to_dict(self):
        return {
            "active_job_id": self.active_job_id,
            "job_status": self.job_status,
            "work_items": [dict(item) for item in self.work_items],
        }


class SleepRuntimeIntegration:
    """Coordinate persistent SleepJob lifecycle with the synchronous Runtime.

    Sleep processing is intentionally stepped. A process call returns control after
    a bounded number of newly committed chunks (one by default), which gives Runtime
    a safe checkpoint boundary where a wake request can interrupt the job without a
    background worker or shared mutable thread state.
    """

    def __init__(
        self,
        *,
        sleep_store,
        executor,
        recovery=None,
        trace=None,
    ):
        if not isinstance(sleep_store, SleepStore):
            raise TypeError("sleep_store must be a SleepStore")
        if not isinstance(executor, SleepChunkExecutor):
            raise TypeError("executor must be a SleepChunkExecutor")
        if executor.sleep_store is not sleep_store:
            raise ValueError("executor must use the same SleepStore")
        if recovery is not None and not isinstance(recovery, SleepRecoveryCoordinator):
            raise TypeError("recovery must be a SleepRecoveryCoordinator or null")
        if recovery is not None and recovery.sleep_store is not sleep_store:
            raise ValueError("recovery must use the same SleepStore")

        self.sleep_store = sleep_store
        self.executor = executor
        self.recovery = recovery
        self.trace = trace
        self._active_job_id = None

    @staticmethod
    def _validate_max_new_chunks(value):
        if value is None:
            return
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("max_new_chunks must be a positive integer or null")

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)

    def activate_job(self, job_id):
        job = self.sleep_store.get_job(job_id)
        if job is None:
            raise ValueError(f"Unknown SleepJob: {job_id}")
        if job["status"] in TERMINAL_JOB_STATUSES:
            raise ValueError(
                f"Cannot activate terminal SleepJob: {job['status']}"
            )
        if self._active_job_id is not None and self._active_job_id != job_id:
            current = self.sleep_store.get_job(self._active_job_id)
            if current is not None and current["status"] not in TERMINAL_JOB_STATUSES:
                raise RuntimeError(
                    f"Another SleepJob is already active: {self._active_job_id}"
                )

        self._active_job_id = job_id
        self._trace(f"sleep-runtime: job {job_id} activated")
        return job

    def enter_sleep(self):
        if self._active_job_id is None:
            self._trace("sleep-runtime: sleeping without active job")
            return None

        job = self.sleep_store.get_job(self._active_job_id)
        if job is None:
            raise ValueError(f"Unknown active SleepJob: {self._active_job_id}")
        if job["status"] in TERMINAL_JOB_STATUSES:
            self._trace(
                f"sleep-runtime: terminal job {job['id']} detached on sleep entry"
            )
            self._active_job_id = None
            return job

        if job["status"] in {"queued", "checkpointed", "interrupted"}:
            job = self.sleep_store.transition_job(
                job["id"],
                "running",
                reason="runtime entered sleep processing",
            )
        elif job["status"] != "running":
            raise ValueError(f"Unsupported active SleepJob status: {job['status']}")

        self._trace(f"sleep-runtime: job {job['id']} running")
        return job

    def _require_active_job(self):
        if self._active_job_id is None:
            raise RuntimeError("No active SleepJob")
        job = self.sleep_store.get_job(self._active_job_id)
        if job is None:
            raise ValueError(f"Unknown active SleepJob: {self._active_job_id}")
        return job

    def _require_active_running_job(self):
        job = self._require_active_job()
        if job["status"] == "checkpointed":
            job = self.sleep_store.transition_job(
                job["id"],
                "running",
                reason="runtime resumed checkpointed sleep work",
            )
        if job["status"] != "running":
            raise RuntimeError(
                f"SleepJob is not running: {job['status']}"
            )
        return job

    def _settle_job_after_work(self, job_id):
        items = self.sleep_store.list_work_items(job_id=job_id)
        statuses = {item.status for item in items}

        if "failed" in statuses:
            target = "failed"
            reason = "sleep work item failed"
        elif items and all(
            item.status in {"completed", "skipped"}
            for item in items
        ):
            target = "completed"
            reason = "all sleep work items completed"
        else:
            target = "checkpointed"
            reason = "sleep work paused at safe checkpoint"

        job = self.sleep_store.get_job(job_id)
        if job["status"] == target:
            return job
        if job["status"] != "running":
            raise RuntimeError(
                "SleepJob changed status during processing: "
                f"{job['status']}"
            )
        return self.sleep_store.transition_job(
            job_id,
            target,
            reason=reason,
        )

    def process_work(
        self,
        work_item_id,
        chunks,
        *,
        max_new_chunks=1,
    ):
        self._validate_max_new_chunks(max_new_chunks)
        active = self._require_active_job()

        work_item = self.sleep_store.get_work_item(work_item_id)
        if work_item is None:
            raise ValueError(f"Unknown WorkItem: {work_item_id}")
        if work_item.job_id != active["id"]:
            raise ValueError(
                "WorkItem does not belong to the active SleepJob"
            )

        job = self._require_active_running_job()
        outcome = self.executor.run(
            work_item_id,
            chunks,
            interrupt_after_new_chunks=max_new_chunks,
        )
        settled = self._settle_job_after_work(job["id"])
        self._trace(
            "sleep-runtime: work "
            f"{work_item_id} -> {outcome.status}, job -> {settled['status']}"
        )
        return outcome

    def prepare_wake(self):
        """Move active SleepJob to an interruptible persistent state before wake."""
        if self._active_job_id is None:
            return None

        job = self.sleep_store.get_job(self._active_job_id)
        if job is None:
            raise ValueError(f"Unknown active SleepJob: {self._active_job_id}")

        if job["status"] in TERMINAL_JOB_STATUSES:
            self._trace(
                f"sleep-runtime: terminal job {job['id']} detached before wake"
            )
            self._active_job_id = None
            return job

        running_items = [
            item
            for item in self.sleep_store.list_work_items(job_id=job["id"])
            if item.status == "running"
        ]
        if running_items:
            if self.recovery is None:
                raise RuntimeError(
                    "Cannot wake while a Sleep WorkItem is running without recovery"
                )
            for item in running_items:
                self.recovery.recover_work_item(item.public_id)

        job = self.sleep_store.get_job(job["id"])
        if job["status"] in {"running", "checkpointed"}:
            job = self.sleep_store.transition_job(
                job["id"],
                "interrupted",
                reason="runtime wake requested",
            )
        elif job["status"] not in {"queued", "interrupted"}:
            raise RuntimeError(
                f"Cannot prepare wake from SleepJob status: {job['status']}"
            )

        self._trace(f"sleep-runtime: job {job['id']} interrupted for wake")
        return job

    def recover(self):
        """Normalize stale running Sleep state after process restart."""
        receipts = []
        recovered_items = []
        if self.recovery is not None:
            receipts = self.recovery.recover_pending()
            for item in self.sleep_store.list_work_items(status="running"):
                recovered_items.append(
                    self.recovery.recover_work_item(item.public_id)
                )

        recovered_jobs = []
        for job in self.sleep_store.list_jobs(status="running"):
            items = self.sleep_store.list_work_items(job_id=job["id"])
            statuses = {item.status for item in items}
            if "running" in statuses:
                raise RuntimeError(
                    f"SleepJob {job['id']} still has running work after recovery"
                )
            if "failed" in statuses:
                target = "failed"
                reason = "runtime recovery found failed work"
            elif items and all(
                item.status in {"completed", "skipped"}
                for item in items
            ):
                target = "completed"
                reason = "runtime recovery found completed work"
            elif "checkpointed" in statuses:
                target = "checkpointed"
                reason = "runtime recovery restored checkpoint boundary"
            else:
                target = "interrupted"
                reason = "runtime recovery restored pre-chunk boundary"
            recovered_jobs.append(
                self.sleep_store.transition_job(
                    job["id"],
                    target,
                    reason=reason,
                )
            )

        if receipts or recovered_items or recovered_jobs:
            self._trace(
                "sleep-runtime: recovery "
                f"receipts={len(receipts)} work_items={len(recovered_items)} "
                f"jobs={len(recovered_jobs)}"
            )
        return {
            "receipts": len(receipts),
            "work_items": len(recovered_items),
            "jobs": len(recovered_jobs),
        }

    def snapshot(self):
        if self._active_job_id is None:
            return SleepRuntimeStatus(
                active_job_id=None,
                job_status=None,
                work_items=(),
            ).to_dict()

        job = self.sleep_store.get_job(self._active_job_id)
        if job is None:
            raise ValueError(f"Unknown active SleepJob: {self._active_job_id}")
        work_items = tuple(
            {
                "id": item.public_id,
                "status": item.status,
                "attempts": item.attempts,
                "checkpoint_ref": item.checkpoint_ref,
            }
            for item in self.sleep_store.list_work_items(job_id=job["id"])
        )
        return SleepRuntimeStatus(
            active_job_id=job["id"],
            job_status=job["status"],
            work_items=work_items,
        ).to_dict()
