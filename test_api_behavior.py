import asyncio
import sys

from agent.api import _execute_plan
from agent.planner import Planner
from agent.tools.exec_cmd import _build_argv, _build_command


def test_frontend_output_plan_request_uses_llm_only():
    result = asyncio.run(Planner(model_instance=object()).plan("来 一个前端输出的plan"))

    assert result["plan"] == [
        {
            "step_id": 1,
            "type": "llm",
            "prompt": result["plan"][0]["prompt"],
        }
    ]
    assert "SSE" in result["plan"][0]["prompt"]


def test_store_state_can_be_final_result():
    plan = [{"step_id": 1, "type": "store_state", "key": "output_path", "value": "frontend_output_example.html"}]
    events = asyncio.run(_collect_async(_execute_plan(plan, model_instance=object())))

    assert events[-1] == {"type": "done", "final_result": "frontend_output_example.html"}


def test_execute_plan_can_disable_auto_repair():
    plan = [{"step_id": 1, "type": "tool", "tool_id": "missing_tool", "params": {}}]
    events = asyncio.run(_collect_async(_execute_plan(plan, model_instance=object(), auto_repair=False)))

    assert not any(event["type"] == "repair_attempt" for event in events)
    assert events[1]["type"] == "tool_result"
    assert events[1]["result"]["success"] is False


def test_news_aggregator_skill_expands_to_python_script():
    class StaticModel:
        async def chat(self, messages, stream=False):
            return (
                '{"plan":[{"step_id":1,"type":"tool","tool_id":"news-aggregator",'
                '"params":{"hours":24,"source":"all","limit":10,"cover":"crawl"}}]}'
            )

    result = asyncio.run(Planner(model_instance=StaticModel()).plan("整理新闻时间线"))
    step = result["plan"][0]

    assert step["tool_id"] == "exec_cmd"
    assert ".venv" in step["params"]["command"]
    assert "scripts" in step["params"]["command"]
    assert "news_fetcher.py" in step["params"]["command"]
    assert step["params"]["cwd"] == "."
    assert step["params"]["args"]["hours"] == 24


def test_skill_expansion_uses_project_venv_not_process_executable(monkeypatch):
    class StaticModel:
        async def chat(self, messages, stream=False):
            return (
                '{"plan":[{"step_id":1,"type":"tool","tool_id":"news-aggregator",'
                '"params":{"hours":24,"source":"kr36","limit":10}}]}'
            )

    monkeypatch.setattr(sys, "executable", r"C:\Users\t21354\Documents\New project 2\.venv\Scripts\python.exe")

    result = asyncio.run(Planner(model_instance=StaticModel()).plan("获取科技新闻时间线"))
    command = result["plan"][0]["params"]["command"]
    assert "New project 2" not in command
    assert "C:\\Users" not in command
    assert ".venv\\Scripts\\python.exe" in command
    assert "skills\\user\\news-aggregator\\scripts\\news_fetcher.py" in command
    assert result["plan"][0]["params"]["cwd"] == "."


def test_planner_rejects_direct_exec_cmd_for_user_skill_script():
    class StaticModel:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, stream=False):
            self.calls += 1
            if self.calls == 1:
                return (
                    '{"plan":[{"step_id":1,"type":"tool","tool_id":"exec_cmd",'
                    '"params":{"command":"python skills/user/news-aggregator/scripts/news_fetcher.py",'
                    '"args":{"hours":24}}},'
                    '{"step_id":2,"type":"llm","prompt":"整理：{{step_1.output}}"}]}'
                )
            return (
                '{"plan":[{"step_id":1,"type":"tool","tool_id":"news-aggregator",'
                '"params":{"hours":24,"source":"kr36","limit":10}},'
                '{"step_id":2,"type":"llm","prompt":"筛选科技相关内容并整理：{{step_1.output}}"}]}'
            )

    result = asyncio.run(Planner(model_instance=StaticModel()).plan("获取科技新闻时间线"))

    assert result["thinking"][1]["action"] == "修正 Plan"
    assert "不要用 exec_cmd 直接运行 skills/user" in result["thinking"][1]["errors"][0]
    assert result["plan"][0]["tool_id"] == "exec_cmd"
    assert "news_fetcher.py" in result["plan"][0]["params"]["command"]


def test_daily_tech_news_timeline_request_is_planned_by_llm_and_expanded():
    class RecordingModel:
        def __init__(self):
            self.messages = None

        async def chat(self, messages, stream=False):
            self.messages = messages
            return (
                '{"plan":['
                '{"step_id":1,"type":"tool","tool_id":"news-aggregator",'
                '"params":{"hours":24,"source":"kr36","limit":20,"cover":"crawl"}},'
                '{"step_id":2,"type":"llm","prompt":"筛选并只保留科技相关内容，基于抓取结果输出当日科技新闻时间线：\\n{{step_1.output}}"}'
                ']}'
            )

    model = RecordingModel()
    result = asyncio.run(Planner(model_instance=model).plan("帮我获取当日科技新闻的时间线"))

    assert model.messages is not None
    assert model.messages[-1]["content"] == "帮我获取当日科技新闻的时间线"

    assert len(result["plan"]) == 2

    fetch_step = result["plan"][0]
    assert fetch_step["type"] == "tool"
    assert fetch_step["tool_id"] == "exec_cmd"
    assert "news_fetcher.py" in fetch_step["params"]["command"]
    assert fetch_step["params"]["args"] == {
        "hours": 24,
        "source": "kr36",
        "limit": 20,
        "cover": "crawl",
    }

    summarize_step = result["plan"][1]
    assert summarize_step["type"] == "llm"
    assert "当日科技新闻时间线" in summarize_step["prompt"]
    assert "{{step_1.output}}" in summarize_step["prompt"]


def test_exec_cmd_builds_boolean_cli_flags():
    command = _build_command("python script.py", {"8d1k": True, "auto_repair": False, "source": "kr36"})

    assert "--8d1k" in command
    assert "True" not in command
    assert "--auto-repair" not in command
    assert "--source kr36" in command


def test_exec_cmd_preserves_quoted_windows_executable_with_spaces():
    argv = _build_argv(
        '"C:\\tmp\\path with spaces\\.venv\\Scripts\\python.exe" '
        "skills\\user\\news-aggregator\\scripts\\news_fetcher.py",
        {"hours": 24, "source": "all", "limit": 20},
    )

    assert argv[0] == "C:\\tmp\\path with spaces\\.venv\\Scripts\\python.exe"
    assert argv[1] == "skills\\user\\news-aggregator\\scripts\\news_fetcher.py"
    assert argv[-6:] == ["--hours", "24", "--source", "all", "--limit", "20"]


async def _collect_async(async_iter):
    return [event async for event in async_iter]
