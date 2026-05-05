from pathlib import Path

META = {
    "tool_id": "read_file",
    "name": "读取文件",
    "description": "读取指定路径的文本文件内容，支持指定行范围",
    "type": "tool",
    "params_schema": {
        "path": {"type": "string", "required": True, "description": "文件绝对或相对路径"},
        "offset": {"type": "integer", "required": False, "default": 1, "description": "起始行号"},
        "n_lines": {"type": "integer", "required": False, "default": 1000, "description": "读取行数"},
    },
}


def execute(path: str, offset: int = 1, n_lines: int = 1000) -> dict:
    p = Path(path)
    if not p.exists():
        return {"success": False, "error": f"文件不存在: {path}"}
    if not p.is_file():
        return {"success": False, "error": f"路径不是文件: {path}"}

    try:
        with open(p, "r", encoding="utf-8") as f:
            lines = f.readlines()
        start = max(0, offset - 1)
        end = min(len(lines), start + n_lines)
        content = "".join(lines[start:end])
        return {"success": True, "content": content, "total_lines": len(lines), "read_lines": end - start}
    except Exception as e:
        return {"success": False, "error": str(e)}
