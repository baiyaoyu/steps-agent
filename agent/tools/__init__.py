"""内置工具注册与发现。"""

import importlib
import pkgutil
from typing import Callable

# 自动导入当前包下所有模块，收集 META 和 execute
_TOOLS: dict[str, dict] = {}
_FUNCTIONS: dict[str, Callable] = {}


def _discover():
    """自动扫描 agent.tools 包下所有模块，注册工具。"""
    import agent.tools as pkg

    for _, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
        if ispkg or modname.startswith("_"):
            continue
        module = importlib.import_module(f"agent.tools.{modname}")
        meta = getattr(module, "META", None)
        execute = getattr(module, "execute", None)
        if meta and execute and "tool_id" in meta:
            _TOOLS[meta["tool_id"]] = meta
            _FUNCTIONS[meta["tool_id"]] = execute


# 模块导入时自动发现
_discover()


def list_tools() -> dict[str, dict]:
    """返回所有内置工具元数据。"""
    return dict(_TOOLS)


def get_tool_meta(tool_id: str) -> dict | None:
    """获取指定工具的元数据。"""
    return _TOOLS.get(tool_id)


def execute_tool(tool_id: str, **kwargs) -> dict:
    """执行指定工具。"""
    fn = _FUNCTIONS.get(tool_id)
    if fn is None:
        return {"success": False, "error": f"未知工具: {tool_id}"}
    return fn(**kwargs)
