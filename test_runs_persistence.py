import asyncio

from fastapi.testclient import TestClient

from agent.api import _redact_log_line, app
from agent.run_store import RunStore, display_event_count, progress_summary


def test_run_store_persists_history_and_events(tmp_path):
    store = RunStore(tmp_path)
    record = store.create({"input": "hello", "mode": "planning"})

    asyncio.run(store.append_event(record["id"], {"type": "thinking", "content": "start"}))
    asyncio.run(store.append_event(record["id"], {"type": "done", "final_result": "ok"}))

    loaded = RunStore(tmp_path)
    history = loaded.list()
    detail = loaded.get(record["id"])

    assert len(history) == 1
    assert history[0]["input"] == "hello"
    assert history[0]["status"] == "done"
    assert detail["events"][0]["type"] == "thinking"
    assert detail["final_result"] == "ok"


def test_run_store_can_resume_from_event_index(tmp_path):
    store = RunStore(tmp_path)
    record = store.create({"input": "resume"})

    asyncio.run(store.append_event(record["id"], {"type": "thinking"}))
    asyncio.run(store.append_event(record["id"], {"type": "plan_generated", "plan": []}))

    async def load_tail():
        _, events = await store.wait_for_events(record["id"], 1)
        return events

    events = asyncio.run(load_tail())
    assert [event["type"] for event in events] == ["plan_generated"]


def test_run_store_error_status_is_terminal(tmp_path):
    store = RunStore(tmp_path)
    record = store.create({"input": "fail"})

    asyncio.run(store.append_event(record["id"], {"type": "error", "message": "boom"}))
    asyncio.run(store.append_event(record["id"], {"type": "done", "final_result": ""}))

    detail = store.get(record["id"])
    summary = store.list()[0]

    assert detail["status"] == "error"
    assert detail["error"] == "boom"
    assert summary["status"] == "error"
    assert summary["excerpt"] == "boom"


def test_run_store_waiter_receives_later_event(tmp_path):
    store = RunStore(tmp_path)
    record = store.create({"input": "wait"})

    async def wait_then_append():
        waiter = asyncio.create_task(store.wait_for_events(record["id"], 0))
        await asyncio.sleep(0)
        await store.append_event(record["id"], {"type": "thinking", "content": "ready"})
        return await asyncio.wait_for(waiter, timeout=1)

    _, events = asyncio.run(wait_then_append())

    assert [event["type"] for event in events] == ["thinking"]


def test_run_store_summary_collapses_streaming_llm_chunks(tmp_path):
    store = RunStore(tmp_path)
    record = store.create({"input": "count"})

    asyncio.run(store.append_event(record["id"], {"type": "llm", "step_id": 1, "content": "a"}))
    asyncio.run(store.append_event(record["id"], {"type": "llm", "step_id": 1, "content": "b"}))
    asyncio.run(store.append_event(record["id"], {"type": "llm", "step_id": 2, "content": "c"}))
    asyncio.run(store.append_event(record["id"], {"type": "done", "final_result": "ok"}))

    summary = store.list()[0]

    assert display_event_count(store.get(record["id"])["events"]) == 3
    assert summary["event_count"] == 3
    assert summary["raw_event_count"] == 4


def test_run_store_summary_reports_step_progress_and_excerpt(tmp_path):
    store = RunStore(tmp_path)
    record = store.create({"input": "progress"})

    asyncio.run(store.append_event(record["id"], {"type": "plan_generated", "plan": [
        {"step_id": 1, "type": "tool", "tool_id": "read_file"},
        {"step_id": 2, "type": "llm", "prompt": "summary"},
    ]}))
    asyncio.run(store.append_event(record["id"], {"type": "tool_result", "step_id": 1, "result": {"success": True}}))
    asyncio.run(store.append_event(record["id"], {"type": "repair_attempt", "step_id": 2}))
    asyncio.run(store.append_event(record["id"], {"type": "llm", "step_id": 2, "content": "done"}))
    asyncio.run(store.append_event(record["id"], {"type": "done", "final_result": "final answer"}))

    summary = store.list()[0]

    assert progress_summary(store.get(record["id"])["events"]) == {
        "total_steps": 2,
        "completed_steps": 2,
        "repair_count": 1,
    }
    assert summary["total_steps"] == 2
    assert summary["completed_steps"] == 2
    assert summary["repair_count"] == 1
    assert summary["excerpt"] == "final answer"


def test_run_store_cleans_stale_tmp_files(tmp_path):
    stale = tmp_path / "stale.tmp"
    stale.write_text("broken", encoding="utf-8")
    store = RunStore(tmp_path)

    store.list()

    assert not stale.exists()


def test_run_apis_are_documented():
    openapi = app.openapi()

    assert "/api/runs" in openapi["paths"]
    assert "/api/runs/execute" in openapi["paths"]
    assert "/api/runs/{run_id}" in openapi["paths"]
    assert "/api/runs/{run_id}/events" in openapi["paths"]
    assert "/api/logs" in openapi["paths"]


def test_logs_endpoint_returns_list():
    client = TestClient(app)
    response = client.get("/api/logs")

    assert response.status_code == 200
    assert isinstance(response.json()["logs"], list)


def test_log_redaction_masks_sensitive_values():
    line = "api_key=sk-secret token: abc123 password='pw123' Authorization: Bearer bearer-token"

    redacted = _redact_log_line(line)

    assert "sk-secret" not in redacted
    assert "abc123" not in redacted
    assert "pw123" not in redacted
    assert "bearer-token" not in redacted
    assert redacted.count("****") == 4


def test_frontend_contains_history_resume_and_visualization_hooks():
    html = open("frontend/index.html", encoding="utf-8").read()
    app_js = open("frontend/app.js", encoding="utf-8").read()

    assert 'id="historyList"' in html
    assert 'id="planGraph"' in html
    assert 'id="eventGraph"' in html
    assert 'class="session-entry"' in html
    assert 'id="newSessionInput"' in html
    assert 'id="newSessionButton" type="button">发起会话' in html
    assert "重新连接" in html
    assert "用此问题新建" in html
    assert "执行规划" in html
    assert 'class="code plan-editor empty"' in html
    assert "localStorage" in app_js
    assert "EventSource" in app_js
    assert "closeSubscription(false)" in app_js
    assert "setActiveRun(runId)" in app_js
    assert "function createParallelRun" in app_js
    assert "function createRun" in app_js
    assert "createRun(body, { open: true })" in app_js
    assert "planInput" in app_js
    assert "function isPlanCurrent" in app_js
    assert "setPlanDraft(data.plan || [], body.input)" in app_js
    assert "Plan 已过期" in app_js
    assert "function reconnectRun" in app_js
    assert "function duplicateRun" in app_js
    assert "function executePlannedRun" in app_js
    assert "function setPlanDraft" in app_js
    assert "function readPlanDraft" in app_js
    assert "function activateTab" in app_js
    assert 'activateTab("plan")' in app_js
    assert 'fetch("/api/runs/execute"' in app_js
    assert "state.plan = Array.isArray(plan)" in app_js
    assert "elements.plan.readOnly = runView || !planCurrent" in app_js
    assert "规划待确认，可在 Plan 阶段编辑 JSON 后执行" in app_js
    assert "Plan 必须是非空 JSON 数组" in app_js
    assert "completed_steps" in app_js
    assert "repair_count" in app_js
    assert "history-excerpt" in app_js
    assert "elements.prompt.readOnly = runView" in app_js
    assert "if (isRunView()) return" in app_js
    assert "closeSubscription(true)" in app_js
    assert "state.activeRunId !== runId" in app_js
    assert "MAX_EVENT_CARDS = 200" in app_js
    assert "MAX_GRAPH_EVENTS = 300" in app_js
    assert "renderEventBatch" in app_js
    assert "for (const event of uniqueEvents) applyEventEffects(event, { appendCard: false, renderGraph: false })" in app_js
    assert "appendEventCard(event, { trim: false })" in app_js
    assert "updateHistorySelection" in app_js
    assert "dataset.runId" in app_js
    assert "/api/runs" in app_js
