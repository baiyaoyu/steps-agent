from pathlib import Path

META = {
    "tool_id": "str_replace",
    "name": "文本替换",
    "description": "在文件中进行字符串替换",
    "type": "tool",
    "params_schema": {
        "path": {"type": "string", "required": True, "description": "文件路径"},
        "old": {"type": "string", "required": True, "description": "要替换的文本"},
        "new": {"type": "string", "required": True, "description": "替换后的文本"},
        "replace_all": {"type": "boolean", "required": False, "default": False, "description": "是否替换全部匹配项"},
    },
}


def execute(path: str, old: str, new: str, replace_all: bool = False) -> dict:
    p = Path(path)
    if not p.exists():
        return {"success": False, "error": f"文件不存在: {path}"}

    try:
        with open(p, "r", encoding="utf-8") as f:
            content = f.read()

        if old not in content:
            return {"success": False, "error": f"未找到要替换的文本: {old[:50]}..."}

        count = 1
        if replace_all:
            new_content = content.replace(old, new)
            count = content.count(old)
        else:
            new_content = content.replace(old, new, 1)

        with open(p, "w", encoding="utf-8") as f:
            f.write(new_content)

        return {"success": True, "replaced_count": count, "path": str(p.absolute())}
    except Exception as e:
        return {"success": False, "error": str(e)}
