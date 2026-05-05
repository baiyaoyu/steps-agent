"""入口分类器：Quick Reply vs Planning。"""

from agent.config import config
from agent.models import create_model


ROUTER_PROMPT = """你是一个意图分类器。请判断用户请求属于以下哪种类型：

- quick_reply: 闲聊、问候、简单问答，不需要工具或复杂规划就能直接回答
- planning: 需要多步骤、工具调用、文件操作、搜索、代码执行等复杂任务
- ambiguous: 意图不明确，需要向用户澄清

请只输出一个单词（quick_reply / planning / ambiguous），不要任何解释。"""


class Router:
    def __init__(self, model_instance=None):
        if model_instance is not None:
            self.model = model_instance
        else:
            self._load_model()

    def _load_model(self):
        provider = config.get("models.default", "deepseek-chat")
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

    async def classify(self, user_input: str, mode: str = "auto") -> str:
        """返回 'quick_reply' 或 'planning' 或 'ambiguous'。"""
        if mode == "quick_reply":
            return "quick_reply"
        if mode == "planning":
            return "planning"

        # auto 模式：先尝试简单规则，再调用 LLM
        stripped = user_input.strip().lower()

        # 简单规则判断
        greetings = ["你好", "hello", "hi", "在吗", "早上好", "晚上好", "谢谢", "再见"]
        if any(stripped.startswith(g) for g in greetings):
            return "quick_reply"

        # 如果包含工具关键词，进入 planning
        tool_keywords = ["搜索", "查找", "读取", "写入", "执行", "运行", "分析", "总结", "生成", "创建"]
        if any(kw in user_input for kw in tool_keywords):
            return "planning"

        # 兜底：调用轻量 LLM 判断
        messages = [
            {"role": "system", "content": ROUTER_PROMPT},
            {"role": "user", "content": user_input},
        ]
        try:
            response = await self.model.chat(messages, stream=False)
            if isinstance(response, str):
                result = response.strip().lower()
                if result in ("quick_reply", "planning", "ambiguous"):
                    return result
        except Exception:
            pass

        return "planning"  # 默认进入 planning，避免遗漏复杂任务
