import asyncio
import shlex
import subprocess
from typing import Any

META = {
    "tool_id": "exec_cmd",
    "name": "命令执行",
    "description": "执行 Shell 命令，也用于执行用户 Skill 脚本",
    "type": "tool",
    "params_schema": {
        "command": {"type": "string", "required": True, "description": "完整的执行命令，必须包含解释器和脚本路径，如 `python3 skills/user/my_skill/exec.py`"},
        "args": {"type": "object", "required": False, "description": "仅用于传递业务参数。字典会被自动转为 `--key value` 格式，列表会按位置传递。不要在此处放入脚本路径或编造不存在的参数。"},
        "description": {"type": "string", "required": False, "description": "命令描述"},
        "timeout": {"type": "integer", "required": False, "default": 60, "description": "超时秒数"},
        "background": {"type": "boolean", "required": False, "default": False, "description": "是否后台执行"},
    },
}


def _build_command(command: str, args: Any) -> str:
    if not args:
        return command
    if isinstance(args, dict):
        arg_str = " ".join(f"--{k} {shlex.quote(str(v))}" for k, v in args.items())
        return f"{command} {arg_str}"
    if isinstance(args, list):
        arg_str = " ".join(shlex.quote(str(v)) for v in args)
        return f"{command} {arg_str}"
    return command


def execute(command: str, args: Any = None, description: str = "", timeout: int = 60, background: bool = False) -> dict:
    full_command = _build_command(command, args)

    if background:
        try:
            proc = subprocess.Popen(
                full_command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return {
                "success": True,
                "pid": proc.pid,
                "command": full_command,
                "background": True,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "command": full_command}

    try:
        result = subprocess.run(
            full_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": full_command,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"命令执行超时({timeout}s)", "command": full_command}
    except Exception as e:
        return {"success": False, "error": str(e), "command": full_command}
