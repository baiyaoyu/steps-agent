# 轻量级动态智能体 —— 后端实现文档

> 供开发者调试和维护使用。

---

## 1. 项目概述

一个轻量级动态智能体后端系统，不依赖 LangGraph 等重型框架。

**核心特性**：
- 内置 7 个基础工具（read_file、write_file、str_replace、exec_cmd、find、oss_upload、tavily_search）
- 用户 Skill 通过 `skills/user/` 目录注册，Planner 懒加载后展开为 `exec_cmd` 调用
- 支持多模型（DeepSeek、Gemini、Qwen）
- SSE 流式输出，事件类型区分 thinking / tool_invoke / tool_result / llm / done
- Planner 规划与 Executor 执行拆分为独立接口

---

## 2. 目录结构

```
agent/
├── __init__.py
├── api.py              # FastAPI HTTP 接口（/api/plan、/api/execute、/api/run）
├── config.py           # 配置读取（config.yaml），支持 ${ENV_VAR} 环境变量注入
├── executor.py         # ExecutionContext（contextvars 封装）+ Plan 执行引擎
├── planner.py          # LLM 规划器，生成 Plan JSON
├── registry.py         # Skill 注册中心，管理 skills/user/ 目录
├── router.py           # 入口分类器（Quick Reply / Planning）
├── models/             # 多模型封装
│   ├── __init__.py
│   ├── base.py         # BaseModel 抽象基类
│   ├── deepseek.py
│   ├── gemini.py
│   └── qwen.py
└── tools/              # 内置工具
    ├── __init__.py     # 自动扫描注册
    ├── read_file.py
    ├── write_file.py
    ├── str_replace.py
    ├── exec_cmd.py     # 也用于执行用户 Skill 脚本
    ├── find.py
    ├── oss_upload.py   # MinIO 实现
    └── tavily_search.py
```

---

## 3. 启动方式

```bash
# 1. 激活虚拟环境
source .venv/bin/activate

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入真实 API Key

# 3. 启动服务
python main.py
```

服务默认监听 `http://0.0.0.0:8000`。

**Swagger UI**：启动后访问 `http://localhost:8000/docs`

---

## 4. API 接口

### 4.1 `POST /api/plan` —— 仅规划

**用途**：调试 Planner，查看生成的 Plan JSON，不执行。

**请求体**：
```json
{
  "input": "帮我搜索轻量级 Agent 框架并总结",
  "mode": "planning"
}
```

**响应**：普通 JSON
```json
{
  "plan": [
    {"step_id": 1, "type": "tool", "tool_id": "tavily_search", "params": {"query": "..."}},
    {"step_id": 2, "type": "llm", "prompt": "总结：{{step_1.output}}"}
  ]
}
```

---

### 4.2 `POST /api/execute` —— 仅执行

**用途**：传入已有的 Plan JSON，由 Executor 顺序执行并 SSE 流式输出。

**请求体**：
```json
{
  "plan": [...],
  "context": {}
}
```

**响应**：`Content-Type: text/event-stream`

```
data: {"type": "tool_invoke", "step_id": 1, "tool_id": "tavily_search", "params": {"query": "..."}}
data: {"type": "tool_result", "step_id": 1, "tool_id": "tavily_search", "result": {...}}
data: {"type": "llm", "step_id": 2, "content": "根据搜索结果..."}
data: {"type": "done", "final_result": "..."}
```

---

### 4.3 `POST /api/run` —— 运行

**用途**：生产接口。Router 分类 → Planner 规划 → Executor 执行，全过程 SSE 流式输出。

**请求体**：
```json
{
  "input": "帮我搜索轻量级 Agent 框架并总结",
  "mode": "auto"
}
```

**响应**：SSE 流（同上）。

**Quick Reply 模式下的 SSE 流**：
```
data: {"type": "thinking", "content": "进入 Quick Reply 模式"}
data: {"type": "llm", "content": "你好！有什么可以帮你的吗？"}
data: {"type": "done", "final_result": "你好！有什么可以帮你的吗？"}
```

---

## 5. SSE 事件类型

| 类型 | 说明 | 字段 |
|------|------|------|
| `thinking` | 思考过程 | `content` |
| `plan_generated` | Planner 完成 | `plan` |
| `tool_invoke` | 开始调用工具 | `step_id`, `tool_id`, `params` |
| `tool_result` | 工具执行完成 | `step_id`, `tool_id`, `result` |
| `llm` | LLM 生成片段 | `step_id`, `content` |
| `state_stored` | 变量存储 | `step_id`, `key`, `value` |
| `error` | 执行错误 | `step_id`, `message` |
| `done` | 全部完成 | `final_result` |

---

## 6. 内置工具清单

| Tool ID | 说明 | 关键参数 |
|---------|------|----------|
| `read_file` | 读取文本文件 | `path`, `offset`, `n_lines` |
| `write_file` | 写入文件 | `path`, `content`, `mode` |
| `str_replace` | 文本替换 | `path`, `old`, `new`, `replace_all` |
| `exec_cmd` | 命令执行 | `command`, `args`（dict/list）, `timeout`, `background` |
| `find` | 文件/内容查找 | `pattern`, `path`, `glob`, `type` |
| `oss_upload` | MinIO 上传 | `local_path`, `remote_key` |
| `tavily_search` | Tavily 搜索 | `query`, `max_results` |

---

## 7. 用户 Skill 开发指南

在 `skills/user/` 下创建子目录，包含 `SKILL.md` 和执行脚本。

### 7.1 SKILL.md 示例

**约定**：`skill_id` 取目录名，无需在 `SKILL.md` 中声明；`type` 固定为 `skill`，无需声明。

```markdown
---
name: 我的技能
description: 简要描述技能用途
dependencies: []
---

## 参数定义

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| input | string | 是 | 输入内容 |

## 执行方式

execution_script: "exec.py"
```

### 7.2 执行脚本示例（exec.py）

```python
#!/usr/bin/env python3
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
args = parser.parse_args()

result = {"message": f"处理完成: {args.input}"}
print(json.dumps(result, ensure_ascii=False))
```

### 7.3 运行机制

1. Registry 扫描 `skills/user/` 目录，**`skill_id` = 目录名**
2. 初始只读取 `SKILL.md` 的 YAML Frontmatter（`name`、`description`、`dependencies`）
3. Planner 确定需要该 Skill 后，Registry 懒加载完整 `SKILL.md`
4. Planner 在 Plan 中直接生成对 `exec_cmd` 的调用：
   ```json
   {"type": "tool", "tool_id": "exec_cmd", "params": {"command": "python3 skills/user/my_skill/exec.py", "args": {"input": "xxx"}}}
   ```
5. `exec_cmd` 将 `args` 字典自动拼接为 `--key value` 格式并执行

---

## 8. 环境变量

复制 `.env.example` 为 `.env` 并填入真实值：

```bash
# 模型 API Key（至少配一个）
DEEPSEEK_API_KEY=...
GEMINI_API_KEY=...
QWEN_API_KEY=...

# Tavily 搜索
TAVILY_API_KEY=...

# MinIO 对象存储
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=agent-bucket
```

---

## 9. 配置文件（config.yaml）

```yaml
agent:
  name: "lightweight-agent"
  skill_dir: "./skills/user"
  default_mode: "auto"

models:
  default: "deepseek-chat"
  planner_model: "deepseek-chat"
  quick_reply_model: "qwen-turbo"
  providers:
    deepseek:
      api_key: "${DEEPSEEK_API_KEY}"
      base_url: "https://api.deepseek.com/v1"
      model: "deepseek-chat"
    gemini:
      api_key: "${GEMINI_API_KEY}"
      base_url: "https://generativelanguage.googleapis.com/v1beta"
      model: "gemini-2.0-flash"
    qwen:
      api_key: "${QWEN_API_KEY}"
      base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
      model: "qwen-max"

search:
  provider: "tavily"
  api_key: "${TAVILY_API_KEY}"

minio:
  endpoint: "${MINIO_ENDPOINT}"
  access_key: "${MINIO_ACCESS_KEY}"
  secret_key: "${MINIO_SECRET_KEY}"
  bucket: "${MINIO_BUCKET}"
```
