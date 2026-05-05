"""集成测试：验证 Registry 懒加载 + skill 执行链路。"""

import asyncio
import sys

sys.path.insert(0, ".")

from agent.config import config
from agent.registry import Registry
from agent.executor import ExecutionContext
from agent.tools import execute_tool


def test_registry_lazy_load():
    print("=== 测试 Registry 懒加载 ===")
    config._data = {"agent": {"skill_dir": "./skills/user"}}

    reg = Registry()
    skills = reg.list_skills()
    print(f"初始扫描发现 Skill 数: {len(skills)}")
    for sid, meta in skills.items():
        print(f"  - {sid}: {meta['name']} | {meta['description']}")

    # 测试懒加载
    detail = reg.lazy_load("example_skill")
    print(f"\n懒加载 example_skill:")
    print(f"  execution_script: {detail.get('execution_script')}")
    print(f"  params_schema: {detail.get('params_schema')}")
    print(f"  dir: {detail.get('dir')}")

    assert detail is not None
    assert detail["execution_script"] == "exec.py"
    print("Registry 懒加载测试通过")


def test_skill_via_exec_cmd():
    print("\n=== 测试通过 exec_cmd 执行用户 Skill ===")
    # 模拟 Planner 生成的 exec_cmd 调用
    result = execute_tool(
        "exec_cmd",
        command="python3 skills/user/example_skill/exec.py",
        args={"input": "Hello from test"}
    )
    print(f"exec_cmd 结果: {result}")
    assert result["success"]
    assert "示例技能处理完成" in result["stdout"]
    print("用户 Skill 执行链路测试通过")


def test_execution_context_with_skill_output():
    print("\n=== 测试 ExecutionContext 引用 Skill 执行结果 ===")
    ctx = ExecutionContext()

    # 模拟执行 skill
    result = execute_tool(
        "exec_cmd",
        command="python3 skills/user/example_skill/exec.py",
        args={"input": "test context"}
    )
    ctx.set_output(1, result)

    # 解析模板
    resolved = ctx.resolve("Skill output: {{step_1.output}}")
    print(f"解析结果: {resolved}")
    assert "示例技能处理完成" in resolved
    print("上下文引用测试通过")


if __name__ == "__main__":
    test_registry_lazy_load()
    test_skill_via_exec_cmd()
    test_execution_context_with_skill_output()
    print("\n=== 所有集成测试通过 ===")
