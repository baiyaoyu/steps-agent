from pathlib import Path

META = {
    "tool_id": "write_file",
    "name": "写入文件",
    "description": "创建新文件或覆盖已有文件",
    "type": "tool",
    "params_schema": {
        "path": {"type": "string", "required": True, "description": "文件路径"},
        "content": {"type": "string", "required": True, "description": "文件内容"},
        "mode": {"type": "string", "required": False, "default": "overwrite", "description": "写入模式: overwrite / append"},
    },
}


def execute(path: str, content: str, mode: str = "overwrite") -> dict:
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        open_mode = "a" if mode == "append" else "w"
        with open(p, open_mode, encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "path": str(p.absolute())}
    except Exception as e:
        return {"success": False, "error": str(e)}
