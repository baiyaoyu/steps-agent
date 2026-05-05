"""HTTP 接口层：FastAPI + SSE 流式输出。"""

import json
from typing import AsyncIterator

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from agent.config import config
from agent.executor import ExecutionContext
from agent.models import create_model
from agent.planner import Planner
from agent.registry import Registry
from agent.router import Router
from agent.tools import execute_tool


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.load()
    yield


# ========== 请求模型（供 Swagger 使用） ==========

class PlanRequest(BaseModel):
    input: str = Field(..., description="用户输入的自然语言请求")
    mode: str = Field("planning", description="模式: auto | quick_reply | planning")
    model: str | None = Field(None, description="指定模型名称（如 deepseek-chat、gemini-2.0-flash、qwen-max），留空使用默认模型")


class ExecuteRequest(BaseModel):
    plan: list = Field(..., description="Plan JSON 数组")
    context: dict = Field(default_factory=dict, description="初始上下文变量")
    model: str | None = Field(None, description="指定模型名称，留空使用默认模型")


class RunRequest(BaseModel):
    input: str = Field(..., description="用户输入的自然语言请求")
    mode: str = Field("auto", description="模式: auto | quick_reply | planning")
    model: str | None = Field(None, description="指定模型名称，留空使用默认模型")


app = FastAPI(title="轻量级动态智能体", lifespan=lifespan)


# ========== 全局异常处理 ==========

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """请求参数校验失败。"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"success": False, "error": "请求参数错误", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """兜底异常处理。"""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"success": False, "error": "服务器内部错误", "message": str(exc)},
    )


def _get_model(model_name: str | None = None):
    """获取模型实例。model_name 留空时使用默认模型。"""
    providers_cfg = config.get("models.providers", {})

    # 如果指定了模型名称，查找对应配置
    if model_name:
        for p_name, p_cfg in providers_cfg.items():
            if p_cfg.get("model") == model_name:
                return create_model(
                    provider=p_name,
                    api_key=p_cfg.get("api_key", ""),
                    base_url=p_cfg.get("base_url", ""),
                    model=model_name,
                )
        raise ValueError(f"未找到模型 '{model_name}' 的配置，请在 config.yaml 中检查 models.providers 配置")

    # 使用默认模型
    provider = config.get("models.default", "deepseek-chat")
    for p_name, p_cfg in providers_cfg.items():
        if p_cfg.get("model") == provider:
            return create_model(
                provider=p_name,
                api_key=p_cfg.get("api_key", ""),
                base_url=p_cfg.get("base_url", ""),
                model=provider,
            )
    p_cfg = providers_cfg.get("deepseek", {})
    return create_model(
        provider="deepseek",
        api_key=p_cfg.get("api_key", ""),
        base_url=p_cfg.get("base_url", ""),
        model=p_cfg.get("model", "deepseek-chat"),
    )


async def _sse_format(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    """将事件字典转为 SSE 格式。"""
    async for event in events:
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _fix_step(model, tool_id: str, original_params: dict, error_message: str) -> dict | None:
    """调用模型修复执行失败的步骤参数。"""
    from agent.tools import get_tool_meta

    meta = get_tool_meta(tool_id)
    description = meta.get("description", "") if meta else ""
    params_schema = meta.get("params_schema", {}) if meta else {}

    fix_prompt = f"""你是一个执行修复器。上一步执行工具时出错了，请分析错误原因并给出修复后的参数。

工具ID: {tool_id}
工具描述: {description}
参数定义: {json.dumps(params_schema, ensure_ascii=False)}
原始参数: {json.dumps(original_params, ensure_ascii=False)}
错误信息: {error_message}

修复规则：
1. 只修改导致错误的参数，不要改动无关参数
2. 如果路径不存在，检查是否使用了正确的相对路径或绝对路径
3. 如果参数类型错误，修正为正确的类型
4. 不要编造不存在的参数
5. 返回格式必须是合法的 JSON，只包含 params 键值对

请只输出修复后的参数 JSON，不要任何解释。"""

    try:
        response = await model.chat([{"role": "user", "content": fix_prompt}], stream=False)
        if isinstance(response, str):
            try:
                fixed = json.loads(response)
                if isinstance(fixed, dict) and "params" in fixed:
                    return fixed["params"]
                return fixed if isinstance(fixed, dict) else None
            except json.JSONDecodeError:
                return None
    except Exception:
        return None
    return None


async def _execute_plan(plan: list[dict], context: ExecutionContext | None = None, model_instance=None) -> AsyncIterator[dict]:
    """执行 Plan 并产生 SSE 事件。"""
    ctx = context or ExecutionContext()
    ExecutionContext.set_current(ctx)

    try:
        model = model_instance or _get_model()
    except Exception as e:
        yield {"type": "error", "message": f"模型初始化失败: {str(e)}"}
        yield {"type": "done", "final_result": ""}
        return

    for step in plan:
        step_id = step.get("step_id", "?")
        step_type = step.get("type", "")

        try:
            if step_type == "tool":
                tool_id = step.get("tool_id", "")
                raw_params = step.get("params", {})
                resolved_params = ctx.resolve(raw_params)

                yield {"type": "tool_invoke", "step_id": step_id, "tool_id": tool_id, "params": resolved_params}
                result = execute_tool(tool_id, **resolved_params)

                # 自动修复：失败后调用模型修复参数，重试一次
                if not result.get("success", False):
                    error_msg = result.get("error", "未知错误")
                    yield {"type": "thinking", "content": f"步骤 {step_id} ({tool_id}) 执行失败: {error_msg}，尝试自动修复..."}

                    try:
                        fixed_params = await _fix_step(model, tool_id, resolved_params, error_msg)
                        if fixed_params:
                            yield {"type": "thinking", "content": f"获取到修复参数: {json.dumps(fixed_params, ensure_ascii=False)}，重试中..."}
                            result = execute_tool(tool_id, **fixed_params)
                            if result.get("success", False):
                                yield {"type": "thinking", "content": f"步骤 {step_id} 自动修复成功"}
                            else:
                                yield {"type": "thinking", "content": f"步骤 {step_id} 修复后仍失败: {result.get('error', '未知错误')}"}
                        else:
                            yield {"type": "thinking", "content": f"步骤 {step_id} 无法生成修复方案，保持原始错误"}
                    except Exception as fix_err:
                        yield {"type": "thinking", "content": f"步骤 {step_id} 自动修复过程出错: {str(fix_err)}"}

                ctx.set_output(step_id, result)
                yield {"type": "tool_result", "step_id": step_id, "tool_id": tool_id, "result": result}

            elif step_type == "llm":
                prompt = step.get("prompt", "")
                resolved_prompt = ctx.resolve(prompt)
                yield {"type": "llm_start", "step_id": step_id, "prompt": resolved_prompt}

                try:
                    full_content = ""
                    response = await model.chat([{"role": "user", "content": resolved_prompt}], stream=True)
                    if hasattr(response, "__aiter__"):
                        async for chunk in response:
                            full_content += chunk
                            yield {"type": "llm", "step_id": step_id, "content": chunk}
                    else:
                        full_content = response
                        yield {"type": "llm", "step_id": step_id, "content": full_content}

                    ctx.set_output(step_id, {"content": full_content})
                except Exception as e:
                    yield {"type": "error", "step_id": step_id, "message": f"LLM 调用失败: {str(e)}"}
                    ctx.set_output(step_id, {"content": "", "error": str(e)})

            elif step_type == "store_state":
                key = step.get("key", "")
                raw_value = step.get("value", "")
                resolved_value = ctx.resolve(raw_value)
                ctx.set_variable(key, resolved_value)
                yield {"type": "state_stored", "step_id": step_id, "key": key, "value": resolved_value}

            else:
                yield {"type": "error", "step_id": step_id, "message": f"未知 Step 类型: {step_type}"}

        except Exception as e:
            yield {"type": "error", "step_id": step_id, "message": f"Step 执行失败: {str(e)}"}

    # 构建最终回复：取最后一步的输出
    final_result = ""
    if plan:
        last_step = plan[-1]
        last_id = str(last_step.get("step_id", ""))
        last_output = ctx.outputs.get(last_id, {})
        if isinstance(last_output, dict):
            final_result = last_output.get("content", last_output.get("stdout", json.dumps(last_output, ensure_ascii=False)))
        else:
            final_result = str(last_output)

    yield {"type": "done", "final_result": final_result}


async def _run_full(user_input: str, mode: str = "auto", model_name: str | None = None) -> AsyncIterator[dict]:
    """完整流程：Router -> Planner -> Executor。"""
    try:
        model_inst = _get_model(model_name) if model_name else _get_model()
    except Exception as e:
        yield {"type": "error", "message": f"模型初始化失败: {str(e)}"}
        yield {"type": "done", "final_result": ""}
        return

    try:
        router = Router(model_instance=model_inst)
        classification = await router.classify(user_input, mode)
    except Exception as e:
        yield {"type": "error", "message": f"意图分类失败: {str(e)}"}
        yield {"type": "done", "final_result": ""}
        return

    if classification == "quick_reply":
        yield {"type": "thinking", "content": "进入 Quick Reply 模式"}
        try:
            full = ""
            response = await model_inst.chat([{"role": "user", "content": user_input}], stream=True)
            if hasattr(response, "__aiter__"):
                async for chunk in response:
                    full += chunk
                    yield {"type": "llm", "content": chunk}
            else:
                full = response
                yield {"type": "llm", "content": full}
            yield {"type": "done", "final_result": full}
        except Exception as e:
            yield {"type": "error", "message": f"Quick Reply 调用失败: {str(e)}"}
            yield {"type": "done", "final_result": ""}
        return

    # Planning 模式
    yield {"type": "thinking", "content": "进入 Planning 模式"}

    try:
        planner = Planner(model_instance=model_inst)
        plan_result = await planner.plan(user_input)
    except Exception as e:
        yield {"type": "error", "message": f"Planner 调用失败: {str(e)}"}
        yield {"type": "done", "final_result": ""}
        return

    # 输出 Planner 的思考过程
    for thinking in plan_result.get("thinking", []):
        yield {"type": "thinking", "content": f"[Planner 第{thinking['round']}轮] {thinking['action']}"}

    if plan_result.get("validation_errors"):
        for err in plan_result["validation_errors"]:
            yield {"type": "thinking", "content": f"[Planner 验证] {err}"}

    plan = plan_result.get("plan", [])

    if not plan:
        yield {"type": "error", "message": "Planner 未能生成有效计划"}
        yield {"type": "done", "final_result": ""}
        return

    yield {"type": "plan_generated", "plan": plan}

    async for event in _execute_plan(plan, model_instance=model_inst):
        yield event


@app.post("/api/plan", summary="仅规划", description="接收用户输入，由 Planner 生成 Plan JSON，不执行。用于调试规划逻辑。")
async def plan_endpoint(req: PlanRequest):
    """仅规划，返回 Plan JSON。"""
    try:
        model_inst = _get_model(req.model) if req.model else None
        planner = Planner(model_instance=model_inst)
        result = await planner.plan(req.input)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": "Planner 调用失败", "message": str(e)},
        )


@app.post("/api/execute", summary="仅执行", description="传入已有的 Plan JSON，由 Executor 顺序执行并 SSE 流式返回执行过程。")
async def execute_endpoint(req: ExecuteRequest):
    """仅执行，SSE 流式输出。"""
    ctx = ExecutionContext()
    ctx.variables.update(req.context)

    try:
        model_inst = _get_model(req.model) if req.model else None
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": "模型初始化失败", "message": str(e)},
        )

    return StreamingResponse(
        _sse_format(_execute_plan(req.plan, ctx, model_instance=model_inst)),
        media_type="text/event-stream",
    )


@app.post("/api/run", summary="运行", description="完整流程：Router 分类 → Planner 规划 → Executor 执行，全过程 SSE 流式输出。")
async def run_endpoint(req: RunRequest):
    """封装接口：plan + execute，SSE 流式输出。"""
    return StreamingResponse(
        _sse_format(_run_full(req.input, req.mode, req.model)),
        media_type="text/event-stream",
    )


@app.get("/api/skills", summary="列出可用能力", description="返回所有内置工具和用户自定义 Skill 的元数据列表。")
async def list_skills_endpoint():
    """列出内置工具 + 用户 Skill。"""
    from agent.tools import list_tools as _list_tools
    from agent.registry import Registry

    tools = _list_tools()
    registry = Registry()
    skills = registry.list_skills()

    result = []
    for tid, meta in tools.items():
        result.append({
            "id": tid,
            "name": meta.get("name", tid),
            "description": meta.get("description", ""),
            "type": "tool",
        })
    for sid, meta in skills.items():
        result.append({
            "id": sid,
            "name": meta.get("name", sid),
            "description": meta.get("description", ""),
            "type": "skill",
        })

    return JSONResponse(content={"skills": result})


@app.get("/api/models", summary="列出可用模型", description="返回配置文件中所有可用的模型列表，API Key 已脱敏处理。")
async def list_models_endpoint():
    """列出可用模型（隐藏 API Key）。"""
    providers_cfg = config.get("models.providers", {})
    default_model = config.get("models.default", "")

    result = []
    for provider_name, p_cfg in providers_cfg.items():
        api_key = p_cfg.get("api_key", "")
        # 脱敏：保留前4位和后4位，中间用 **** 替换
        if len(api_key) > 12:
            masked_key = api_key[:4] + "****" + api_key[-4:]
        elif len(api_key) > 0:
            masked_key = "****"
        else:
            masked_key = ""

        result.append({
            "provider": provider_name,
            "model": p_cfg.get("model", ""),
            "base_url": p_cfg.get("base_url", ""),
            "api_key": masked_key,
            "is_default": p_cfg.get("model", "") == default_model,
        })

    return JSONResponse(content={"models": result, "default": default_model})
