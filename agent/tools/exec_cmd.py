import asyncio
import os
from pathlib import Path
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
        "cwd": {"type": "string", "required": False, "description": "执行工作目录，默认项目根目录"},
        "timeout": {"type": "integer", "required": False, "default": 60, "description": "超时秒数"},
        "background": {"type": "boolean", "required": False, "default": False, "description": "是否后台执行"},
    },
}


def _build_command(command: str, args: Any) -> str:
    if not args:
        return command
    quote_args = subprocess.list2cmdline if os.name == "nt" else lambda parts: " ".join(shlex.quote(str(part)) for part in parts)
    if isinstance(args, dict):
        parts = []
        for k, v in args.items():
            if v is None or v is False:
                continue
            option = str(k).replace("_", "-")
            parts.append(f"--{option}")
            if v is not True:
                parts.append(str(v))
        arg_str = quote_args(parts)
        return f"{command} {arg_str}"
    if isinstance(args, list):
        arg_str = quote_args([str(v) for v in args])
        return f"{command} {arg_str}"
    return command


def _split_command(command: str) -> list[str]:
    command = command.strip()
    if not command:
        return []

    if os.name == "nt" and command.startswith('"'):
        end = command.find('"', 1)
        if end != -1:
            first = command[1:end]
            rest = command[end + 1 :].strip()
            if not rest:
                return [first]
            return [first] + [part.strip('"') for part in shlex.split(rest, posix=False)]

    return [part.strip('"') for part in shlex.split(command, posix=os.name != "nt")]


def _args_to_parts(args: Any) -> list[str]:
    if not args:
        return []
    if isinstance(args, dict):
        parts = []
        for k, v in args.items():
            if v is None or v is False:
                continue
            option = str(k).replace("_", "-")
            parts.append(f"--{option}")
            if v is not True:
                parts.append(str(v))
        return parts
    if isinstance(args, list):
        return [str(v) for v in args]
    return []


def _build_argv(command: str, args: Any) -> list[str]:
    return _split_command(command) + _args_to_parts(args)


def _should_use_shell(argv: list[str]) -> bool:
    if os.name != "nt" or not argv:
        return False
    return argv[0].lower() in {"echo", "dir", "copy", "del", "type", "set"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_cwd(cwd: str | None = None) -> str:
    if not cwd:
        return str(_project_root())
    path = Path(cwd)
    if not path.is_absolute():
        path = _project_root() / path
    return str(path)


def execute(command: str, args: Any = None, description: str = "", cwd: str | None = None, timeout: int = 60, background: bool = False) -> dict:
    full_command = _build_command(command, args)
    argv = _build_argv(command, args)
    use_shell = _should_use_shell(argv)
    run_target = full_command if use_shell else argv
    run_cwd = _resolve_cwd(cwd)

    if background:
        try:
            proc = subprocess.Popen(
                run_target,
                shell=use_shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=run_cwd,
            )
            return {
                "success": True,
                "pid": proc.pid,
                "command": full_command,
                "cwd": run_cwd,
                "background": True,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "command": full_command, "cwd": run_cwd}

    try:
        result = subprocess.run(
            run_target,
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=run_cwd,
        )
        payload = {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": full_command,
            "cwd": run_cwd,
        }
        if result.returncode != 0:
            payload["error"] = result.stderr.strip() or result.stdout.strip() or f"returncode={result.returncode}"
        return payload
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"命令执行超时({timeout}s)", "command": full_command, "cwd": run_cwd}
    except Exception as e:
        return {"success": False, "error": str(e), "command": full_command, "cwd": run_cwd}
