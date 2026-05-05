import os

import httpx

META = {
    "tool_id": "tavily_search",
    "name": "Tavily 搜索",
    "description": "通过 Tavily API 搜索网络信息",
    "type": "tool",
    "params_schema": {
        "query": {"type": "string", "required": True, "description": "搜索关键词"},
        "max_results": {"type": "integer", "required": False, "default": 5, "description": "返回结果数量"},
    },
}


def execute(query: str, max_results: int = 5) -> dict:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {"success": False, "error": "TAVILY_API_KEY 环境变量未设置"}

    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
            })
        return {
            "success": True,
            "query": query,
            "results": formatted,
            "count": len(formatted),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
