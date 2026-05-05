"""基础集成测试。"""

import asyncio
import sys

sys.path.insert(0, ".")

from agent.config import config
from agent.tools import list_tools, execute_tool
from agent.executor import ExecutionContext
from agent.registry import Registry


def test_config():
    print("=== 测试配置读取 ===")
    try:
        config.load("config.yaml")
        print("配置加载成功")
        print(f"agent.name = {config.get('agent.name')}")
    except FileNotFoundError:
        print("config.yaml 不存在，使用空配置")
        config._data = {
            "agent": {"name": "test-agent", "skill_dir": "./skills/user"},
            "models": {
                "default": "deepseek-chat",
                "providers": {
                    "deepseek": {
                        "api_key": "test-key",
                        "base_url": "https://api.deepseek.com/v1",
                        "model": "deepseek-chat",
                    }
                }
            }
        }


def test_tools():
    print("\n=== 测试内置工具 ===")
    tools = list_tools()
    print(f"注册工具数: {len(tools)}")
    for tid in tools:
        print(f"  - {tid}")

    # 测试 write_file
    result = execute_tool("write_file", path="/tmp/test_agent.txt", content="hello world")
    print(f"write_file: {result}")
    assert result["success"]

    # 测试 read_file
    result = execute_tool("read_file", path="/tmp/test_agent.txt")
    print(f"read_file: {result}")
    assert result["success"]
    assert "hello world" in result["content"]

    # 测试 str_replace
    result = execute_tool("str_replace", path="/tmp/test_agent.txt", old="world", new="agent")
    print(f"str_replace: {result}")
    assert result["success"]

    # 验证替换
    result = execute_tool("read_file", path="/tmp/test_agent.txt")
    assert "hello agent" in result["content"]

    # 测试 exec_cmd
    result = execute_tool("exec_cmd", command="echo", args=["hello"])
    print(f"exec_cmd: {result}")
    assert result["success"]
    assert "hello" in result["stdout"]

    print("内置工具测试通过")


def test_execution_context():
    print("\n=== 测试 ExecutionContext ===")
    ctx = ExecutionContext()
    ctx.set_output(1, {"content": "step1 result"})
    ctx.set_output(2, {"stdout": "step2 output"})
    ctx.set_variable("topic", "AI Agent")

    # 测试模板解析
    resolved = ctx.resolve("Result: {{step_1.output}}")
    print(f"解析 {{step_1.output}} = {resolved}")
    assert "step1 result" in resolved

    resolved = ctx.resolve("Output: {{step_2.output}}")
    print(f"解析 {{step_2.output}} = {resolved}")
    assert "step2 output" in resolved

    resolved = ctx.resolve("Topic: ${topic}")
    print(f"解析 ${{topic}} = {resolved}")
    assert "AI Agent" in resolved

    print("ExecutionContext 测试通过")


def test_registry():
    print("\n=== 测试 Registry ===")
    reg = Registry("./skills/user")
    skills = reg.list_skills()
    print(f"发现 Skill 数: {len(skills)}")
    for sid, meta in skills.items():
        print(f"  - {sid}: {meta['name']}")
    print("Registry 测试通过")


async def test_api_plan():
    print("\n=== 测试 /api/plan 接口 ===")
    from agent.planner import Planner
    planner = Planner()
    # 由于需要真实 API Key，这里只测试接口可用性
    print("Planner 实例化成功")


if __name__ == "__main__":
    test_config()
    test_tools()
    test_execution_context()
    test_registry()
    # test_api_plan 需要真实模型，暂不自动运行
    print("\n=== 所有基础测试通过 ===")
