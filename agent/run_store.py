import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from agent.logging_config import get_logger


RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
logger = get_logger(__name__)


def display_event_count(events: list[dict[str, Any]]) -> int:
    """Count user-meaningful events, collapsing streaming chunks."""
    count = 0
    collapsed_streams = set()
    for event in events:
        event_type = event.get("type", "")
        if event_type == "llm":
            key = ("llm", event.get("step_id", ""))
            if key in collapsed_streams:
                continue
            collapsed_streams.add(key)
        count += 1
    return count


def progress_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    """Summarize step progress without counting streaming noise."""
    plan_steps: set[str] = set()
    completed_steps: set[str] = set()
    repair_count = 0
    for event in events:
        event_type = event.get("type", "")
        if event_type == "plan_generated":
            for step in event.get("plan") or []:
                step_id = step.get("step_id")
                if step_id is not None:
                    plan_steps.add(str(step_id))
        if event_type in {"tool_result", "state_stored"}:
            step_id = event.get("step_id")
            if step_id is not None:
                completed_steps.add(str(step_id))
        if event_type == "llm":
            step_id = event.get("step_id")
            if step_id is not None and event.get("content"):
                completed_steps.add(str(step_id))
        if event_type in {"repair_attempt", "step_repaired", "repair_failed"}:
            repair_count += 1
    return {
        "total_steps": len(plan_steps),
        "completed_steps": len(completed_steps & plan_steps) if plan_steps else len(completed_steps),
        "repair_count": repair_count,
    }


def result_excerpt(record: dict[str, Any], max_length: int = 160) -> str:
    text = record.get("error") or record.get("final_result") or ""
    text = " ".join(str(text).split())
    return text[:max_length]


class RunStore:
    def __init__(self, runs_dir: Path | None = None):
        self.runs_dir = runs_dir or RUNS_DIR
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._conditions: dict[str, asyncio.Condition] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def create(self, request: dict[str, Any]) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        now = time.time()
        record = {
            "id": run_id,
            "created_at": now,
            "updated_at": now,
            "status": "queued",
            "request": request,
            "events": [],
            "final_result": "",
            "error": "",
        }
        self._write(record)
        logger.info("run_created id=%s input=%r", run_id, request.get("input", "")[:200])
        return record

    def list(self) -> list[dict[str, Any]]:
        records = []
        self._cleanup_tmp_files()
        for path in sorted(self.runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                record = self._read_path(path)
            except Exception:
                logger.exception("failed_to_read_run path=%s", path)
                continue
            records.append(self._summary(record))
        return records

    def get(self, run_id: str) -> dict[str, Any] | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        return self._read_path(path)

    def set_task(self, run_id: str, task: asyncio.Task):
        self._tasks[run_id] = task

    def is_running(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return bool(task and not task.done())

    async def append_event(self, run_id: str, event: dict[str, Any]):
        condition = self._condition(run_id)
        async with condition:
            record = self.get(run_id)
            if record is None:
                logger.error("append_event_missing_run id=%s event=%s", run_id, event.get("type"))
                return

            event = dict(event)
            event.setdefault("index", len(record["events"]))
            event.setdefault("timestamp", time.time())
            record["events"].append(event)
            record["updated_at"] = time.time()

            event_type = event.get("type")
            if event_type in {"tool_result", "error", "repair_failed"}:
                logger.info("run_event id=%s type=%s payload=%s", run_id, event_type, json.dumps(event, ensure_ascii=False)[:2000])
            if event_type == "error":
                record["status"] = "error"
                record["error"] = event.get("message") or event.get("error") or "unknown error"
                logger.error("run_error id=%s error=%s", run_id, record["error"])
            elif event_type == "done":
                record["final_result"] = event.get("final_result", "")
                if record.get("status") != "error":
                    record["status"] = "done"
                logger.info("run_done id=%s final_len=%s", run_id, len(str(record["final_result"])))
            elif record["status"] == "queued":
                record["status"] = "running"

            self._write(record)
            condition.notify_all()

    def mark_running(self, run_id: str):
        record = self.get(run_id)
        if not record:
            return
        record["status"] = "running"
        record["updated_at"] = time.time()
        self._write(record)

    def mark_failed(self, run_id: str, error: str):
        record = self.get(run_id)
        if not record:
            return
        record["status"] = "error"
        record["error"] = error
        record["updated_at"] = time.time()
        self._write(record)
        logger.exception("run_failed id=%s error=%s", run_id, error)

    async def wait_for_events(self, run_id: str, from_index: int):
        condition = self._condition(run_id)
        while True:
            async with condition:
                record = self.get(run_id)
                if record is None:
                    return None, []
                events = record.get("events", [])
                if len(events) > from_index or record.get("status") in {"done", "error"}:
                    return record, events[from_index:]
                await condition.wait()

    def _summary(self, record: dict[str, Any]) -> dict[str, Any]:
        request = record.get("request", {})
        events = record.get("events", [])
        progress = progress_summary(events)
        return {
            "id": record.get("id", ""),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "status": record.get("status", ""),
            "input": request.get("input", ""),
            "mode": request.get("mode", ""),
            "model": request.get("model"),
            "event_count": display_event_count(events),
            "raw_event_count": len(events),
            "total_steps": progress["total_steps"],
            "completed_steps": progress["completed_steps"],
            "repair_count": progress["repair_count"],
            "excerpt": result_excerpt(record),
            "final_result": record.get("final_result", ""),
            "error": record.get("error", ""),
        }

    def _condition(self, run_id: str) -> asyncio.Condition:
        if run_id not in self._conditions:
            self._conditions[run_id] = asyncio.Condition()
        return self._conditions[run_id]

    def _path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"

    def _write(self, record: dict[str, Any]):
        path = self._path(record["id"])
        tmp = self.runs_dir / f".{record['id']}.{uuid.uuid4().hex}.tmp"
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        last_error = None
        for _ in range(5):
            try:
                tmp.replace(path)
                return
            except PermissionError as e:
                last_error = e
                time.sleep(0.05)
        try:
            tmp.unlink(missing_ok=True)
        finally:
            if last_error:
                raise last_error

    def _read_path(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _cleanup_tmp_files(self):
        for path in self.runs_dir.glob("*.tmp"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        for path in self.runs_dir.glob(".*.tmp"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


run_store = RunStore()
