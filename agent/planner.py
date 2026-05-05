"""规划器：ReAct 风格，生成 → 验证 → 修正（最多 3 轮，收敛目标=格式合法就停）。"""

import json
import re

from agent.config import config
from agent.models import create_model
from agent.registry import Registry
from agent.tools import list_tools


SYSTEM_PROMPT = """你是一个任务规划器。请根据用户请求和可用工具列表，生成一个执行计划（Plan JSON）。

## 输出格式示例

```json
{
  "plan": [
    {"step_id": 1, "type": "tool", "tool_id": "tavily_search", "params": {"query": "轻量级 Agent 框架", "max_results": 5}},
    {"step_id": 2, "type": "tool", "tool_id": "read_file", "params": {"path": "README.md"}},
    {"step_id": 3, "type": "llm", "prompt": "基于以下内容生成摘要：\\n{{step_1.output}}"},
    {"step_id": 4, "type": "store_state", "key": "summary", "value": "{{step_3.output}}"}
  ]
}
```

## 格式规则（必须严格遵守）

1. 每个步骤必须有 `type` 字段，值为 `"tool"`、`"llm"` 或 `"store_state"`
2. `type="tool"` 时必须有 `tool_id` 和 `params`
3. `type="llm"` 时必须有 `prompt`
4. `type="store_state"` 时必须有 `key` 和 `value`
5. 步骤间传递结果使用 `{{step_N.output}}` 语法
6. 调用用户自定义 Skill 时，`tool_id` 写 Skill 的目录名，`params` 只传业务参数
7. 输出必须是合法 JSON，不要 markdown 代码块，不要注释

## 可用工具

{tools_desc}

## 用户自定义 Skill

{skills_desc}

请只输出 Plan JSON，不要任何解释。"""


FIX_PROMPT = """你之前生成的 Plan 存在格式问题，请严格按照下面的格式规则重新生成。

## 之前发现的问题

{errors}

## 格式规则（必须严格遵守）

1. 每个步骤必须有 `type` 字段，值为 `"tool"`、`"llm"` 或 `"store_state"`
2. `type="tool"` 时必须有 `tool_id` 和 `params`（params 是对象）
3. `type="llm"` 时必须有 `prompt`
4. `type="store_state"` 时必须有 `key` 和 `value`
5. 步骤间传递结果使用 `{{step_N.output}}` 语法
6. 调用用户自定义 Skill 时，`tool_id` 写 Skill 的目录名，`params` 只传业务参数
7. 输出必须是合法 JSON，不要 markdown 代码块，不要注释

## 输出格式示例

```json
{
  "plan": [
    {"step_id": 1, "type": "tool", "tool_id": "tavily_search", "params": {"query": "..."}},
    {"step_id": 2, "type": "llm", "prompt": "总结：{{step_1.output}}"}
  ]
}
```

## 可用工具

{tools_desc}

## 用户自定义 Skill

{skills_desc}

请重新输出正确的 Plan JSON，不要任何解释。"""


def _format_tools() -> str:
    tools = list_tools()
    lines = []
    for tid, meta in tools.items():
        lines.append(f"- {tid}: {meta.get('name', '')} - {meta.get('description', '')}")
        schema = meta.get("params_schema", {})
        if schema:
            for k, v in schema.items():
                req = "必填" if v.get("required") else f"可选，默认{v.get('default', '无')}"
                lines.append(f"  参数 {k}: {v.get('description', '')} ({req})")
    return "\n".join(lines)


def _format_skills(skills: dict) -> str:
    if not skills:
        return "无"
    lines = []
    for sid, meta in skills.items():
        lines.append(f"- {sid}: {meta.get('name', '')} - {meta.get('description', '')}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出中提取 JSON。"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    return None


class Planner:
    def __init__(self, registry: Registry | None = None, model_instance=None):
        self.registry = registry or Registry()
        if model_instance is not None:
            self.model = model_instance
        else:
            self._load_model()
        self.thinking_steps: list[dict] = []

    def _load_model(self):
        provider = config.get("models.planner_model", config.get("models.default", "deepseek-chat"))
        providers_cfg = config.get("models.providers", {})
        for p_name, p_cfg in providers_cfg.items():
            if p_cfg.get("model") == provider:
                self.model = create_model(
                    provider=p_name,
                    api_key=p_cfg.get("api_key", ""),
                    base_url=p_cfg.get("base_url", ""),
                    model=provider,
                )
                return
        p_cfg = providers_cfg.get("deepseek", {})
        self.model = create_model(
            provider="deepseek",
            api_key=p_cfg.get("api_key", ""),
            base_url=p_cfg.get("base_url", ""),
            model=p_cfg.get("model", "deepseek-chat"),
        )

    async def plan(self, user_input: str) -> dict:
        """ReAct 风格规划：生成 → 验证 → 修正（最多 3 轮，收敛目标=格式合法）。"""
        self.thinking_steps = []
        tools_desc = _format_tools()
        skills_meta = self.registry.list_skills()
        skills_desc = _format_skills(skills_meta)

        available_tool_ids = set(list_tools().keys())
        available_skill_ids = set(skills_meta.keys())

        plan = []
        validation_errors = []

        for attempt in range(3):
            if attempt == 0:
                self.thinking_steps.append({"round": 1, "action": "生成初稿 Plan"})
                prompt = SYSTEM_PROMPT.replace("{tools_desc}", tools_desc).replace("{skills_desc}", skills_desc)
                messages = [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_input},
                ]
            else:
                self.thinking_steps.append({"round": attempt + 1, "action": "修正 Plan", "errors": validation_errors})
                fix_prompt = FIX_PROMPT.replace("{errors}", "\n".join(f"- {e}" for e in validation_errors)).replace("{tools_desc}", tools_desc).replace("{skills_desc}", skills_desc)
                messages = [
                    {"role": "system", "content": fix_prompt},
                    {"role": "user", "content": user_input},
                ]

            response = await self.model.chat(messages, stream=False)
            plan_obj = _extract_json(response) if isinstance(response, str) else None

            if plan_obj is None:
                validation_errors = ["无法生成合法的 JSON"]
                continue

            plan = plan_obj.get("plan", [])
            if not plan:
                validation_errors = ["plan 数组为空"]
                continue

            # 验证：只检查格式和基本合法性，不追求完美
            validation_errors = self._validate_plan(plan, available_tool_ids, available_skill_ids)

            if not validation_errors:
                self.thinking_steps.append({"round": attempt + 1, "action": "验证通过"})
                break

        # 后处理：展开 Skill 为 exec_cmd
        plan = await self._expand_skills(plan)

        result = {"plan": plan, "thinking": self.thinking_steps}
        if validation_errors:
            result["error"] = "Planner 经过多次修正后仍存在问题"
            result["validation_errors"] = validation_errors

        return result

    def _validate_plan(self, plan: list[dict], available_tool_ids: set, available_skill_ids: set) -> list[str]:
        """验证 Plan 的格式合法性（收敛目标：格式对就行）。"""
        errors = []
        step_ids = set()

        for i, step in enumerate(plan):
            if not isinstance(step, dict):
                errors.append(f"第 {i+1} 个步骤不是对象")
                continue

            step_id = step.get("step_id")
            if step_id is not None:
                if step_id in step_ids:
                    errors.append(f"步骤 ID {step_id} 重复")
                step_ids.add(step_id)

            step_type = step.get("type", "")
            if not step_type:
                errors.append(f"步骤 {step_id or i+1} 缺少 type 字段")
                continue

            if step_type == "tool":
                tool_id = step.get("tool_id", "")
                if not tool_id:
                    errors.append(f"步骤 {step_id or i+1} (tool) 缺少 tool_id")
                elif tool_id not in available_tool_ids and tool_id not in available_skill_ids:
                    errors.append(f"步骤 {step_id or i+1} tool_id '{tool_id}' 不存在")

                params = step.get("params")
                if params is not None and not isinstance(params, dict):
                    errors.append(f"步骤 {step_id or i+1} params 必须是对象")

            elif step_type == "llm":
                if not step.get("prompt", ""):
                    errors.append(f"步骤 {step_id or i+1} (llm) 缺少 prompt")

            elif step_type == "store_state":
                if not step.get("key", ""):
                    errors.append(f"步骤 {step_id or i+1} (store_state) 缺少 key")

            else:
                errors.append(f"步骤 {step_id or i+1} 未知 type: '{step_type}'，必须是 tool/llm/store_state")

        # 验证上下文引用（宽松检查）
        for step in plan:
            if not isinstance(step, dict):
                continue
            step_id = step.get("step_id", "?")
            text = json.dumps(step, ensure_ascii=False)
            refs = re.findall(r"\{\{step_(\d+(?:\.\d+)?)\.(\w+)\}\}", text)
            all_step_ids = [str(s.get("step_id", "")) for s in plan if isinstance(s, dict)]
            for ref_step_id, _field in refs:
                if ref_step_id not in all_step_ids:
                    errors.append(f"步骤 {step_id} 引用了不存在的步骤 {{step_{ref_step_id}.output}}")

        return errors

    async def _expand_skills(self, plan: list[dict]) -> list[dict]:
        """将 Plan 中使用用户 Skill 的步骤展开为 exec_cmd 调用。"""
        result = []
        for step in plan:
            if not isinstance(step, dict):
                result.append(step)
                continue

            tool_id = step.get("tool_id", "")
            params = step.get("params", {})

            if self.registry.list_skills().get(tool_id):
                detail = self.registry.lazy_load(tool_id)
                if detail:
                    dir_path = detail.get("dir", "")
                    script = detail.get("execution_script", "")
                    interpreter = detail.get("interpreter", "")

                    script_path = f"{dir_path}/{script}" if dir_path and script else script
                    if interpreter:
                        command = f"{interpreter} {script_path}"
                    else:
                        command = script_path

                    skill_params = {k: v for k, v in params.items() if k not in ("skill_id",)}

                    new_step = {
                        "type": "tool",
                        "tool_id": "exec_cmd",
                        "params": {
                            "command": command,
                            "args": skill_params,
                        },
                    }
                    if "step_id" in step:
                        new_step["step_id"] = step["step_id"]
                    if "description" in step:
                        new_step["description"] = step["description"]
                    result.append(new_step)
                    continue

            result.append(step)
        return result
