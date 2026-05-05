"""执行器：顺序执行 Plan，管理上下文，推送 SSE 事件。"""

import contextvars
import json
import re
from typing import AsyncIterator

from agent.tools import execute_tool


class ExecutionContext:
    """执行上下文，使用 contextvars 封装。"""

    _ctx = contextvars.ContextVar("agent_execution_context", default=None)

    def __init__(self):
        self.outputs: dict[str, dict] = {}      # step_id -> tool output dict
        self.variables: dict[str, any] = {}     # store_state 变量

    @classmethod
    def get_current(cls) -> "ExecutionContext | None":
        return cls._ctx.get()

    @classmethod
    def set_current(cls, ctx: "ExecutionContext"):
        cls._ctx.set(ctx)

    def set_output(self, step_id: str | int, output: dict):
        self.outputs[str(step_id)] = output

    def set_variable(self, key: str, value: any):
        self.variables[key] = value

    def resolve(self, obj: any) -> any:
        """递归解析对象中的模板语法 {{step_N.output}} 和 ${var_name}。"""
        if isinstance(obj, str):
            return self._resolve_str(obj)
        if isinstance(obj, dict):
            return {k: self.resolve(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.resolve(v) for v in obj]
        return obj

    def _resolve_str(self, text: str) -> str:
        # 解析 {{step_N.output}}
        def replacer_step(match):
            step_id = match.group(1)
            field = match.group(2)
            data = self.outputs.get(step_id, {})
            if field == "output":
                # output 可以是 dict 或 str，优先取 content 字段，否则 str 化
                val = data
                if isinstance(val, dict):
                    if "content" in val:
                        return str(val["content"])
                    if "stdout" in val:
                        return str(val["stdout"])
                    return json.dumps(val, ensure_ascii=False)
                return str(val)
            return str(data.get(field, ""))

        text = re.sub(r"\{\{step_(\d+(?:\.\d+)?)\.(\w+)\}\}", replacer_step, text)

        # 解析 ${var_name}
        def replacer_var(match):
            key = match.group(1)
            val = self.variables.get(key)
            if val is None:
                return match.group(0)
            if isinstance(val, (dict, list)):
                return json.dumps(val, ensure_ascii=False)
            return str(val)

        text = re.sub(r"\$\{(\w+)\}", replacer_var, text)
        return text


async def execute_plan(plan: list[dict], context: ExecutionContext | None = None) -> AsyncIterator[dict]:
    """顺序执行 Plan，产生 SSE 事件。"""
    if context is None:
        context = ExecutionContext()
    ExecutionContext.set_current(context)

    for step in plan:
        step_id = step.get("step_id", "?")
        step_type = step.get("type", "")

        if step_type == "tool":
            tool_id = step.get("tool_id", "")
            raw_params = step.get("params", {})
            resolved_params = context.resolve(raw_params)

            yield {"type": "tool_invoke", "step_id": step_id, "tool_id": tool_id, "params": resolved_params}

            result = execute_tool(tool_id, **resolved_params)
            context.set_output(step_id, result)

            yield {"type": "tool_result", "step_id": step_id, "tool_id": tool_id, "result": result}

        elif step_type == "llm":
            prompt = step.get("prompt", "")
            resolved_prompt = context.resolve(prompt)

            # LLM 调用由上层（api.py）注入，executor 本身不直接调用模型
            # 这里只产生事件，实际流式生成在外部处理
            yield {"type": "llm_start", "step_id": step_id, "prompt": resolved_prompt}
            # 占位：外部需要消费 llm_start 后自行调用模型并推送 llm 片段
            # 为简化，executor 假设 llm 结果已通过某种方式回写
            # 实际实现中，api 层需要特殊处理 llm step
            context.set_output(step_id, {"content": ""})  # 占位

        elif step_type == "store_state":
            key = step.get("key", "")
            raw_value = step.get("value", "")
            resolved_value = context.resolve(raw_value)
            context.set_variable(key, resolved_value)
            yield {"type": "state_stored", "step_id": step_id, "key": key, "value": resolved_value}

        else:
            yield {"type": "error", "step_id": step_id, "message": f"未知 Step 类型: {step_type}"}

    yield {"type": "done", "final_result": context.outputs}
