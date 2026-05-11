"""Skill 注册中心：管理 skills/user/ 目录下的用户自定义 Skill。

约定：
- skill_id = 目录名称（约定优于配置）
- type = "skill"（无需声明）
- 元数据从 SKILL.md 的 YAML Frontmatter 读取
- 支持 dependencies 字段声明依赖
"""

import re
from pathlib import Path

import yaml


class Registry:
    """用户 Skill 注册中心。"""

    def __init__(self, skill_dir: str | None = None):
        if skill_dir is None:
            from agent.config import config
            skill_dir = config.get("agent.skill_dir", "./skills/user")
        self.skill_dir = Path(skill_dir)
        self._meta_cache: dict[str, dict] = {}  # skill_id -> 元数据
        self._detail_cache: dict[str, dict] = {}  # skill_id -> 完整解析结果

    def scan(self) -> dict[str, dict]:
        """扫描 skill 目录，读取 YAML Frontmatter 元数据。

        skill_id 取目录名，无需在 SKILL.md 中声明。
        """
        if not self.skill_dir.exists():
            return {}

        for subdir in self.skill_dir.iterdir():
            if not subdir.is_dir():
                continue
            skill_md = subdir / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                meta = self._parse_frontmatter(skill_md)
                skill_id = subdir.name  # 约定：目录名即 skill_id
                self._meta_cache[skill_id] = {
                    "skill_id": skill_id,
                    "name": meta.get("name", skill_id),
                    "description": meta.get("description", ""),
                    "type": "skill",  # 约定
                    "dependencies": meta.get("dependencies", []),
                    "execution_script": meta.get("execution_script", ""),
                    "interpreter": meta.get("interpreter", ""),
                    "params_schema": meta.get("params_schema", {}),
                    "dir": str(subdir),
                }
            except Exception:
                continue

        return dict(self._meta_cache)

    def list_skills(self) -> dict[str, dict]:
        """返回已扫描的 skill 元数据列表。"""
        if not self._meta_cache:
            self.scan()
        return dict(self._meta_cache)

    def lazy_load(self, skill_id: str) -> dict | None:
        """按需加载指定 Skill 的完整内容。"""
        if not self._meta_cache:
            self.scan()

        if skill_id in self._detail_cache:
            return self._detail_cache[skill_id]

        meta = self._meta_cache.get(skill_id)
        if meta is None:
            return None

        skill_md = Path(meta["dir"]) / "SKILL.md"
        try:
            detail = self._parse_full(skill_md)
            detail["skill_id"] = skill_id
            detail["dir"] = meta["dir"]
            self._detail_cache[skill_id] = detail
            return detail
        except Exception:
            return None

    @staticmethod
    def _parse_frontmatter(path: Path) -> dict:
        """解析 SKILL.md 的 YAML Frontmatter。"""
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not match:
            return {}

        try:
            return yaml.safe_load(match.group(1)) or {}
        except Exception:
            return {}

    @staticmethod
    def _parse_full(path: Path) -> dict:
        """解析完整的 SKILL.md 内容。"""
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        meta = {}
        body = content
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if match:
            try:
                meta = yaml.safe_load(match.group(1)) or {}
            except Exception:
                pass
            body = match.group(2)

        result = {
            "name": meta.get("name", ""),
            "description": meta.get("description", ""),
            "dependencies": meta.get("dependencies", []),
            "execution_script": meta.get("execution_script", ""),
            "interpreter": meta.get("interpreter", ""),
            "params_schema": meta.get("params_schema", {}),
        }

        # 如果 frontmatter 中没有 execution_script，尝试从 body 中提取
        if not result["execution_script"]:
            m = re.search(r"execution_script:\s*\"?([^\"\n]+)\"?", body)
            if m:
                result["execution_script"] = m.group(1).strip()

        return result
