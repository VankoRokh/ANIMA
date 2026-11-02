"""Stage 6 Task ↔ Sleep lifecycle integration without changing Stage 3 stores."""

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from anima.diagnostics.trace import DiagnosticTrace
from anima.execution.store import ExecutionStore
from anima.runtime import Runtime
from anima.tasks.contracts import validate_goal_id, validate_task_id
from anima.tasks.store import TaskStore


SCHEMA_VERSION = 1
LINK_ID_PREFIX = "tsl_"
LINK_STATUSES = {"attached", "sleeping", "awake", "closed", "failed"}
TERMINAL_LINK_STATUSES = {"closed", "failed"}
ALLOWED_LINK_TRANSITIONS = {
    "attached": {"sleeping", "awake", "failed"},
    "sleeping": {"awake", "closed", "failed"},
    "awake": {"sleeping", "closed", "failed"},
    "closed": set(),
    "failed": set(),
}
UNSAFE_EXECUTION_STATUSES = {"prepared", "executing", "uncertain"}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_sleep_links (
    row_id INTEGER PRIMARY KEY,
    public_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    sleep_job_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN ('attached', 'sleeping', 'awake', 'closed', 'failed')
    ),
    status_reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_task_sleep_one_open_per_task
    ON task_sleep_links(task_id)
    WHERE status IN ('attached', 'sleeping', 'awake');
CREATE INDEX IF NOT EXISTS idx_task_sleep_status
    ON task_sleep_links(status, created_at, row_id);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _validate_timestamp(value, label):
    value = _require_text(value, label)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return value


def _validate_link_id(value):
    if not isinstance(value, str) or not value.startswith(LINK_ID_PREFIX):
        raise ValueError("TaskSleepLink public_id must be a tsl_UUIDv4")
    raw = value[len(LINK_ID_PREFIX):]
    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError) as error:
        raise ValueError("TaskSleepLink public_id must be a tsl_UUIDv4") from error
    if parsed.version != 4 or str(parsed) != raw:
        raise ValueError("TaskSleepLink public_id must be a tsl_UUIDv4")
    return value


def _validate_sleep_job_id(value):
    if not isinstance(value, str) or not value.startswith("sj_"):
        raise ValueError("TaskSleepLink sleep_job_id must be a sj_UUIDv4")
    raw = value[3:]
    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError) as error:
        raise ValueError("TaskSleepLink sleep_job_id must be a sj_UUIDv4") from error
    if parsed.version != 4 or str(parsed) != raw:
        raise ValueError("TaskSleepLink sleep_job_id must be a sj_UUIDv4")
    return value


@dataclass(frozen=True, slots=True)
class TaskSleepLink:
    public_id: str
    task_id: str
    goal_id: str
    sleep_job_id: str
    status: str
    status_reason: str
    created_at: str
    updated_at: str

    def __post_init__(self):
        _validate_link_id(self.public_id)
        validate_task_id(self.task_id)
        if validate_goal_id(self.goal_id) is None:
            raise ValueError("TaskSleepLink goal_id must be a Goal UUIDv4")
        _validate_sleep_job_id(self.sleep_job_id)
        if self.status not in LINK_STATUSES:
            raise ValueError(f"Unknown TaskSleepLink status: {self.status!r}")
        object.__setattr__(
            self,
            "status_reason",
            _require_text(self.status_reason, "TaskSleepLink status_reason"),
        )
        object.__setattr__(
            self,
            "created_at",
            _validate_timestamp(self.created_at, "TaskSleepLink created_at"),
        )
        object.__setattr__(
            self,
            "updated_at",
            _validate_timestamp(self.updated_at, "TaskSleepLink updated_at"),
        )
        if datetime.fromisoformat(self.updated_at) < datetime.fromisoformat(self.created_at):
            raise ValueError("TaskSleepLink updated_at cannot precede created_at")


class TaskSleepLinkStore:
    """Persist only Task/Goal/SleepJob association and bridge phase."""

    def __init__(self, database_file):
        self.database_file = Path(database_file)
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_file)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def transaction(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def _initialize(self):
        try:
            with closing(self._connect()) as connection, connection:
                connection.executescript(SCHEMA_SQL)
                row = connection.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
                elif row["value"] != str(SCHEMA_VERSION):
                    raise ValueError(
                        f"Unsupported TaskSleepLink schema in {self.database_file}"
                    )
        except ValueError:
            raise
        except sqlite3.DatabaseError as error:
            raise ValueError(
                f"Cannot initialize TaskSleepLink database {self.database_file}: {error}"
            ) from error

    @staticmethod
    def _row(row):
        if row is None:
            return None
        return TaskSleepLink(
            public_id=row["public_id"],
            task_id=row["task_id"],
            goal_id=row["goal_id"],
            sleep_job_id=row["sleep_job_id"],
            status=row["status"],
            status_reason=row["status_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def schema_version(self):
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return int(row["value"])

    def create_link(
        self,
        *,
        task_id,
        goal_id,
        sleep_job_id,
        reason="sleep lifecycle attached",
        timestamp=None,
        public_id=None,
    ):
        validate_task_id(task_id)
        if validate_goal_id(goal_id) is None:
            raise ValueError("TaskSleepLink goal_id must be a Goal UUIDv4")
        _validate_sleep_job_id(sleep_job_id)
        reason = _require_text(reason, "TaskSleepLink creation reason")
        timestamp = _validate_timestamp(timestamp or _now(), "TaskSleepLink timestamp")
        public_id = _validate_link_id(public_id or f"{LINK_ID_PREFIX}{uuid4()}")
        link = TaskSleepLink(
            public_id=public_id,
            task_id=task_id,
            goal_id=goal_id,
            sleep_job_id=sleep_job_id,
            status="attached",
            status_reason=reason,
            created_at=timestamp,
            updated_at=timestamp,
        )
        try:
            with self.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO task_sleep_links(
                        public_id, task_id, goal_id, sleep_job_id, status,
                        status_reason, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'attached', ?, ?, ?)
                    """,
                    (
                        link.public_id,
                        link.task_id,
                        link.goal_id,
                        link.sleep_job_id,
                        link.status_reason,
                        link.created_at,
                        link.updated_at,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Cannot create TaskSleepLink: {error}") from error
        return self.get_link(public_id)

    def get_link(self, public_id):
        _validate_link_id(public_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM task_sleep_links WHERE public_id = ?",
                (public_id,),
            ).fetchone()
        return self._row(row)

    def get_open_for_task(self, task_id):
        validate_task_id(task_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT * FROM task_sleep_links
                WHERE task_id = ? AND status IN ('attached', 'sleeping', 'awake')
                ORDER BY row_id DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
        return self._row(row)

    def get_by_job(self, sleep_job_id):
        _validate_sleep_job_id(sleep_job_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM task_sleep_links WHERE sleep_job_id = ?",
                (sleep_job_id,),
            ).fetchone()
        return self._row(row)

    def list_open(self):
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT * FROM task_sleep_links
                WHERE status IN ('attached', 'sleeping', 'awake')
                ORDER BY created_at, row_id
                """
            ).fetchall()
        return [self._row(row) for row in rows]

    def transition(self, public_id, to_status, *, reason, timestamp=None):
        _validate_link_id(public_id)
        if to_status not in LINK_STATUSES:
            raise ValueError(f"Unknown TaskSleepLink status: {to_status!r}")
        reason = _require_text(reason, "TaskSleepLink transition reason")
        timestamp = _validate_timestamp(timestamp or _now(), "TaskSleepLink timestamp")
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM task_sleep_links WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown TaskSleepLink: {public_id}")
            current = row["status"]
            if to_status not in ALLOWED_LINK_TRANSITIONS[current]:
                raise ValueError(
                    f"Invalid TaskSleepLink transition: {current} -> {to_status}"
                )
            if datetime.fromisoformat(timestamp) < datetime.fromisoformat(row["updated_at"]):
                raise ValueError("TaskSleepLink transition cannot move backward in time")
            cursor = connection.execute(
                """
                UPDATE task_sleep_links
                SET status = ?, status_reason = ?, updated_at = ?
                WHERE public_id = ? AND status = ?
                """,
                (to_status, reason, timestamp, public_id, current),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"TaskSleepLink changed concurrently: {public_id}")
        return self.get_link(public_id)


@dataclass(frozen=True, slots=True)
class TaskSleepTurn:
    link: TaskSleepLink
    task_status: str
    goal_status: str
    sleep_job_status: str
    anima_status: str


class TaskSleepCoordinator:
    """System-owned bridge around the already-proven Stage 3 Sleep runtime."""

    def __init__(
        self,
        *,
        runtime,
        task_store,
        link_store,
        execution_store,
        trace=None,
    ):
        if not isinstance(runtime, Runtime):
            raise TypeError("TaskSleepCoordinator runtime must be Runtime")
        if runtime.sleep_runtime is None:
            raise ValueError("TaskSleepCoordinator requires configured Sleep runtime")
        if runtime.internal_state is None:
            raise ValueError("TaskSleepCoordinator requires configured Internal State runtime")
        if not isinstance(task_store, TaskStore):
            raise TypeError("TaskSleepCoordinator task_store must be TaskStore")
        if not isinstance(link_store, TaskSleepLinkStore):
            raise TypeError("TaskSleepCoordinator link_store must be TaskSleepLinkStore")
        if not isinstance(execution_store, ExecutionStore):
            raise TypeError("TaskSleepCoordinator execution_store must be ExecutionStore")
        if trace is not None and not isinstance(trace, DiagnosticTrace):
            raise TypeError("TaskSleepCoordinator trace must be DiagnosticTrace or null")
        self.runtime = runtime
        self.task_store = task_store
        self.link_store = link_store
        self.execution_store = execution_store
        self.trace = trace

    def _task_goal(self, task_id, *, required_task_status=None):
        task = self.task_store.get_task(task_id)
        if task is None:
            raise ValueError(f"Unknown Task: {task_id}")
        if required_task_status is not None and task.status != required_task_status:
            raise ValueError(
                f"Sleep lifecycle requires Task {required_task_status!r}, got {task.status!r}"
            )
        if task.goal_id is None:
            raise ValueError("Sleep lifecycle requires Task linked to Goal")
        goal = self.runtime.internal_state.goals.get_goal(task.goal_id)
        if goal is None:
            raise ValueError(f"Unknown Goal: {task.goal_id}")
        return task, goal

    @staticmethod
    def _require_active_goal(goal):
        if goal["status"] != "active":
            raise ValueError(
                f"Sleep lifecycle requires active Goal, got {goal['status']!r}"
            )

    def _require_safe_execution_boundary(self, task_id):
        unsafe = [
            item
            for item in self.execution_store.list_operations(task_id=task_id)
            if item["status"] in UNSAFE_EXECUTION_STATUSES
        ]
        if unsafe:
            statuses = ", ".join(sorted({item["status"] for item in unsafe}))
            raise RuntimeError(
                "Sleep requires no prepared/executing/uncertain execution operation; "
                f"found {statuses}"
            )

    def _sleep_job(self, job_id):
        job = self.runtime.sleep_runtime.sleep_store.get_job(job_id)
        if job is None:
            raise ValueError(f"Unknown SleepJob: {job_id}")
        return job

    def _turn(self, link):
        task = self.task_store.get_task(link.task_id)
        goal = self.runtime.internal_state.goals.get_goal(link.goal_id)
        job = self.runtime.sleep_runtime.sleep_store.get_job(link.sleep_job_id)
        return TaskSleepTurn(
            link=link,
            task_status=task.status,
            goal_status=goal["status"],
            sleep_job_status=job["status"],
            anima_status=self.runtime.anima.get()["status"],
        )

    def request_sleep(self, task_id, sleep_job_id, *, timestamp=None):
        task, goal = self._task_goal(task_id, required_task_status="active")
        self._require_active_goal(goal)
        self._require_safe_execution_boundary(task.public_id)
        job = self._sleep_job(sleep_job_id)
        if self.runtime.anima.get()["status"] == "sleeping":
            raise RuntimeError("Cannot attach Task to Sleep while ANIMA is already sleeping")

        open_link = self.link_store.get_open_for_task(task.public_id)
        by_job = self.link_store.get_by_job(job["id"])
        if open_link is None:
            if by_job is not None:
                raise RuntimeError("SleepJob is already bound to another lifecycle")
            if job["status"] != "queued":
                raise ValueError(
                    f"New Task/Sleep link requires queued SleepJob, got {job['status']!r}"
                )
            link = self.link_store.create_link(
                task_id=task.public_id,
                goal_id=task.goal_id,
                sleep_job_id=job["id"],
                reason="Stage 6 sleep intent committed",
                timestamp=timestamp,
            )
        else:
            link = open_link
            if link.sleep_job_id != job["id"] or link.goal_id != task.goal_id:
                raise RuntimeError("Task already has a different open Sleep lifecycle")
            if link.status != "awake":
                raise RuntimeError(
                    f"Task Sleep lifecycle cannot re-enter from {link.status!r}"
                )
            if by_job is None or by_job.public_id != link.public_id:
                raise RuntimeError("SleepJob lifecycle binding is inconsistent")
            if job["status"] != "interrupted":
                raise ValueError(
                    f"Sleep resume requires interrupted SleepJob, got {job['status']!r}"
                )

        self.task_store.transition_task(
            task.public_id,
            "interrupted",
            reason=f"sleep lifecycle {link.public_id} entered",
            source_id=link.public_id,
            timestamp=timestamp,
        )
        self.runtime.activate_sleep_job(job["id"])
        self.runtime.sleep()
        link = self.link_store.transition(
            link.public_id,
            "sleeping",
            reason="runtime entered Sleep",
            timestamp=timestamp,
        )
        self._trace(
            "task-sleep: entered "
            f"link={link.public_id} task={task.public_id} goal={task.goal_id} "
            f"job={job['id']}"
        )
        return self._turn(link)

    def wake(self, task_id, *, timestamp=None):
        link = self.link_store.get_open_for_task(task_id)
        if link is None:
            raise ValueError(f"Task has no open Sleep lifecycle: {task_id}")
        if link.status != "sleeping":
            raise RuntimeError(f"Wake requires sleeping lifecycle, got {link.status!r}")
        task, goal = self._task_goal(task_id)
        if task.goal_id != link.goal_id:
            raise ValueError("Task Goal no longer matches Sleep lifecycle link")
        self._require_active_goal(goal)
        self._require_safe_execution_boundary(task.public_id)

        if self.runtime.anima.get()["status"] == "sleeping":
            self.runtime.wake()
        else:
            self.runtime.sleep_runtime.prepare_wake()

        task = self.task_store.get_task(task.public_id)
        if task.status != "interrupted":
            raise ValueError(
                f"Wake resume requires interrupted Task, got {task.status!r}"
            )
        self.task_store.transition_task(
            task.public_id,
            "active",
            reason=f"sleep lifecycle {link.public_id} resumed",
            source_id=link.public_id,
            timestamp=timestamp,
        )
        job = self._sleep_job(link.sleep_job_id)
        if job["status"] == "completed":
            target = "closed"
            reason = "SleepJob completed; Task resumed"
        elif job["status"] == "failed":
            target = "failed"
            reason = "SleepJob failed; Task resumed without Sleep result"
        else:
            target = "awake"
            reason = "Task awake; SleepJob remains resumable"
        link = self.link_store.transition(
            link.public_id,
            target,
            reason=reason,
            timestamp=timestamp,
        )
        self._trace(
            "task-sleep: wake "
            f"link={link.public_id} task={task.public_id} goal={task.goal_id} "
            f"job={link.sleep_job_id} link_status={link.status}"
        )
        return self._turn(link)

    def recover(self):
        """Recover Stage 3 sleep state and reconnect persistent Task/Sleep links."""
        sleep_recovery = self.runtime.sleep_runtime.recover()
        restored = 0
        normalized_awake = 0
        for link in self.link_store.list_open():
            task, goal = self._task_goal(link.task_id)
            if task.goal_id != link.goal_id:
                raise ValueError("Recovered Task Goal does not match Sleep lifecycle link")
            job = self._sleep_job(link.sleep_job_id)
            anima_status = self.runtime.anima.get()["status"]

            if link.status == "attached":
                if task.status == "active":
                    self.task_store.transition_task(
                        task.public_id,
                        "interrupted",
                        reason=f"recover committed sleep lifecycle {link.public_id}",
                        source_id=link.public_id,
                    )
                    task = self.task_store.get_task(task.public_id)
                if anima_status == "sleeping":
                    if job["status"] not in {"completed", "failed"}:
                        self.runtime.sleep_runtime.activate_job(job["id"])
                    self.link_store.transition(
                        link.public_id,
                        "sleeping",
                        reason="recovered committed Sleep state",
                    )
                    restored += 1
            elif link.status == "sleeping":
                if anima_status == "sleeping":
                    if job["status"] not in {"completed", "failed"}:
                        self.runtime.sleep_runtime.activate_job(job["id"])
                    restored += 1
                else:
                    self._require_active_goal(goal)
                    if task.status == "interrupted":
                        self.task_store.transition_task(
                            task.public_id,
                            "active",
                            reason=f"recover wake lifecycle {link.public_id}",
                            source_id=link.public_id,
                        )
                    elif task.status != "active":
                        raise ValueError(
                            "Recovered sleeping link with awake Runtime has unsupported "
                            f"Task status: {task.status!r}"
                        )
                    target = (
                        "closed"
                        if job["status"] == "completed"
                        else "failed"
                        if job["status"] == "failed"
                        else "awake"
                    )
                    self.link_store.transition(
                        link.public_id,
                        target,
                        reason="recovery found Runtime already awake",
                    )
                    normalized_awake += 1
            elif link.status == "awake":
                if anima_status != "awake":
                    raise RuntimeError(
                        "Open awake TaskSleepLink conflicts with sleeping Runtime state"
                    )
                if task.status != "active":
                    raise ValueError(
                        f"Open awake TaskSleepLink requires active Task, got {task.status!r}"
                    )

        self._trace(
            "task-sleep: recovery "
            f"sleep_jobs={sleep_recovery['jobs']} restored={restored} "
            f"normalized_awake={normalized_awake}"
        )
        return {
            "sleep": sleep_recovery,
            "restored": restored,
            "normalized_awake": normalized_awake,
        }

    def _trace(self, message):
        if self.trace is not None:
            self.trace.record(message)


__all__ = [
    "TaskSleepCoordinator",
    "TaskSleepLink",
    "TaskSleepLinkStore",
    "TaskSleepTurn",
]
