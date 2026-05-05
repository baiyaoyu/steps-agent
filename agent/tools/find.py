import fnmatch
import os
from pathlib import Path

META = {
    "tool_id": "find",
    "name": "查找",
    "description": "按文件名模式或内容搜索文件",
    "type": "tool",
    "params_schema": {
        "pattern": {"type": "string", "required": True, "description": "搜索模式"},
        "path": {"type": "string", "required": False, "default": ".", "description": "搜索起始路径"},
        "glob": {"type": "string", "required": False, "description": "文件匹配模式，如 *.py"},
        "type": {"type": "string", "required": False, "default": "name", "description": "搜索类型: name(文件名) | content(文件内容)"},
    },
}


def execute(pattern: str, path: str = ".", glob: str = "", type: str = "name") -> dict:
    root = Path(path)
    if not root.exists():
        return {"success": False, "error": f"路径不存在: {path}"}

    matches = []

    try:
        if type == "name":
            for current, _dirs, files in os.walk(root):
                for name in files + _dirs:
                    if fnmatch.fnmatch(name, pattern):
                        matches.append(str(Path(current) / name))
                    if glob and fnmatch.fnmatch(name, glob):
                        matches.append(str(Path(current) / name))
            # 去重
            matches = list(dict.fromkeys(matches))
        elif type == "content":
            for current, _dirs, files in os.walk(root):
                for name in files:
                    if glob and not fnmatch.fnmatch(name, glob):
                        continue
                    file_path = Path(current) / name
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        if pattern in content:
                            matches.append(str(file_path))
                    except Exception:
                        continue
        else:
            return {"success": False, "error": f"不支持的搜索类型: {type}"}

        return {"success": True, "matches": matches, "count": len(matches)}
    except Exception as e:
        return {"success": False, "error": str(e)}
