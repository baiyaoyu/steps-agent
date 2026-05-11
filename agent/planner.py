"""规划器：ReAct 风格，生成 → 验证 → 修正（最多 3 轮，收敛目标=格式合法就停）。"""

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from agent.config import config
from agent.models import create_model
from agent.registry import Registry
from agent.tools import list_tools


SYSTEM_PROMPT = """你是一个任务规划器。请根据用户请求和可用工具列表，生成一个执行计划（Plan JSON）。

## 规划策略

1. 精确理解用户要的是“执行任务”还是“输出一个计划/方案”。如果用户要求“输出 plan / 给我一个计划 / 前端输出的 plan”，通常只需要 `llm` 步骤生成计划内容，不要擅自搜索、写文件或执行命令。
2. 只有用户明确要求联网查询、最新资料、搜索资料、当前信息时，才使用 `tavily_search`。
3. 只有用户明确要求保存、写入、生成文件、落盘时，才使用 `write_file`。
4. 如果某个 `llm` 步骤的输出会被 `write_file` 写入文件，prompt 必须明确要求“只输出目标文件内容，不要 Markdown 代码块，不要解释文字”。
5. 如果用户要求“时间线、摘要、报告、整理、分析、解读”等面向人的最终内容，先用工具获取资料，再增加 `llm` 步骤基于 `{{step_N.output}}` 生成最终内容；不要只停在工具原始输出。
6. 如果用户指定了领域、主题或类别（例如科技、财经、政策、体育），最终 `llm` 步骤必须要求筛选并只保留该领域相关内容，丢弃工具结果中的无关条目。
7. 当用户询问前端如何消费本系统输出时，优先生成面向 SSE 事件的前端处理计划，覆盖 `thinking`、`plan_generated`、`tool_invoke`、`tool_result`、`llm`、`error`、`done` 等事件。

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
6. 调用用户自定义 Skill 时，`tool_id` 写 Skill 的目录名，`params` 只传业务参数；不要用 `exec_cmd` 手写或猜测 Skill 脚本路径
7. `exec_cmd` 只用于没有现成工具或 Skill 覆盖的通用命令；如果可用 Skill 能完成任务，必须直接调用该 Skill ID
8. 输出必须是合法 JSON，不要 markdown 代码块，不要注释

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
6. 调用用户自定义 Skill 时，`tool_id` 写 Skill 的目录名，`params` 只传业务参数；不要用 `exec_cmd` 手写或猜测 Skill 脚本路径
7. `exec_cmd` 只用于没有现成工具或 Skill 覆盖的通用命令；如果可用 Skill 能完成任务，必须直接调用该 Skill ID
8. 输出必须是合法 JSON，不要 markdown 代码块，不要注释

## 规划策略

1. 用户要求输出计划/方案时，优先用 `llm` 生成计划内容，不要擅自搜索、写文件或执行命令。
2. 只有用户明确要求搜索/最新/当前信息时，才使用 `tavily_search`。
3. 只有用户明确要求保存/写入/生成文件时，才使用 `write_file`。
4. 如果用户要求“时间线、摘要、报告、整理、分析、解读”等面向人的最终内容，工具获取资料后必须增加 `llm` 步骤基于 `{{step_N.output}}` 生成最终内容。
5. 如果用户指定了领域、主题或类别，最终 `llm` 步骤必须要求筛选并只保留该领域相关内容，丢弃无关条目。
6. 如果 `llm` 输出会被写入文件，要求它只输出目标文件内容，不要 Markdown 代码块和解释文字。

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
        schema = meta.get("params_schema", {})
        if schema:
            for k, v in schema.items():
                req = "必填" if v.get("required") else f"可选，默认{v.get('default', '无')}"
                lines.append(f"  参数 {k}: {v.get('description', '')} ({req})")
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


def _is_frontend_output_plan_request(user_input: str) -> bool:
    """Recognize requests that ask for a frontend output plan, not execution."""
    text = user_input.lower().replace(" ", "")
    wants_frontend = "前端" in text or "frontend" in text
    wants_plan = "plan" in text or "计划" in text or "方案" in text
    asks_execution = any(word in text for word in ("搜索", "查询", "保存", "写入", "生成文件", "落盘", "创建文件"))
    return wants_frontend and wants_plan and not asks_execution


def _frontend_output_plan() -> list[dict]:
    return [
        {
            "step_id": 1,
            "type": "llm",
            "prompt": (
                "请输出一个前端消费本系统 /api/run SSE 流的实现计划。"
                "内容要覆盖：请求方式、SSE data 行解析、按事件类型渲染 thinking/plan_generated/"
                "tool_invoke/tool_result/llm/error/done、llm 分片拼接、错误处理、取消请求、"
                "以及最小可用 UI 状态结构。只输出计划内容，不要调用工具。"
            ),
        }
    ]


def _requires_llm_final_output(user_input: str) -> bool:
    text = user_input.lower().replace(" ", "")
    return any(
        word in text
        for word in (
            "时间线",
            "timeline",
            "摘要",
            "总结",
            "报告",
            "整理",
            "分析",
            "解读",
            "timeline",
            "summary",
            "report",
            "analyze",
        )
    )


def _quote_command_part(part: str) -> str:
    """Quote one command token for the current platform."""
    if os.name == "nt":
        return f'"{part}"' if any(ch.isspace() for ch in part) else part
    return shlex.quote(part)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _python_interpreter_for_skill() -> str:
    if os.name == "nt":
        local_python = Path(".venv") / "Scripts" / "python.exe"
    else:
        local_python = Path(".venv") / "bin" / "python"
    if (_project_root() / local_python).exists():
        return str(local_python)
    return "python"


def _relative_to_project(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(_project_root())
        return str(rel)
    except ValueError:
        return str(path)


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

        if _is_frontend_output_plan_request(user_input):
            self.thinking_steps.append({"round": 1, "action": "命中前端输出 Plan 规则"})
            self.thinking_steps.append({"round": 1, "action": "验证通过"})
            return {"plan": _frontend_output_plan(), "thinking": self.thinking_steps}

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
            validation_errors = self._validate_plan(plan, available_tool_ids, available_skill_ids, user_input)

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

    def _validate_plan(
        self,
        plan: list[dict],
        available_tool_ids: set,
        available_skill_ids: set,
        user_input: str = "",
    ) -> list[str]:
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
                if tool_id == "exec_cmd" and isinstance(params, dict):
                    command = str(params.get("command", ""))
                    normalized = command.replace("\\", "/")
                    if "skills/user/" in normalized:
                        errors.append(
                            f"步骤 {step_id or i+1} 不要用 exec_cmd 直接运行 skills/user 下的脚本；"
                            "请直接使用已注册的 Skill ID 作为 tool_id"
                        )

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

        if _requires_llm_final_output(user_input):
            has_tool = any(isinstance(step, dict) and step.get("type") == "tool" for step in plan)
            has_llm = any(isinstance(step, dict) and step.get("type") == "llm" for step in plan)
            if has_tool and not has_llm:
                errors.append(
                    "用户需要面向人的最终内容，不能只返回工具原始结果；"
                    "请在工具步骤之后增加 llm 步骤，基于 {{step_N.output}} 生成最终回答"
                )

        normalized_user_input = user_input.lower().replace(" ", "")
        if "科技" in normalized_user_input or "tech" in normalized_user_input:
            llm_prompts = [
                str(step.get("prompt", ""))
                for step in plan
                if isinstance(step, dict) and step.get("type") == "llm"
            ]
            if llm_prompts:
                prompt_text = "\n".join(llm_prompts).lower()
                has_domain = "科技" in prompt_text or "tech" in prompt_text
                has_filter = any(word in prompt_text for word in ("只保留", "筛选", "过滤", "相关", "discard", "filter"))
                if not (has_domain and has_filter):
                    errors.append(
                        "用户指定了科技领域，最终 llm 步骤必须要求筛选并只保留科技相关内容，"
                        "丢弃工具结果中的无关新闻"
                    )

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

                    if not script:
                        result.append(step)
                        continue

                    script_path = _relative_to_project(Path(dir_path) / script) if dir_path else script
                    if interpreter:
                        interpreter_cmd = _python_interpreter_for_skill() if interpreter in ("python", "python3") else interpreter
                        command = f"{_quote_command_part(interpreter_cmd)} {_quote_command_part(script_path)}"
                    elif script_path.endswith(".py"):
                        command = f"{_quote_command_part(_python_interpreter_for_skill())} {_quote_command_part(script_path)}"
                    else:
                        command = _quote_command_part(script_path)

                    skill_params = {k: v for k, v in params.items() if k not in ("skill_id",)}

                    new_step = {
                        "type": "tool",
                        "tool_id": "exec_cmd",
                        "params": {
                            "command": command,
                            "args": skill_params,
                            "cwd": ".",
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
