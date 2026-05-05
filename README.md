# 轻量级动态智能体 —— 规格说明与实现计划

> 基于 `lightweight-agent-design-1.md`、`lightweight-agent-design-2.md` 及后续需求整理

---

## 1. 设计目标

构建一个 **Token 高效、架构轻量、内置工具 + 用户 Skill 扩展** 的动态智能体后端系统。对简单请求直接流式回复，对复杂请求动态规划并流式执行。

**核心原则**：
- 不引入重型智能体框架（无 LangGraph 兼容层）。
- 常用基础工具直接内建在后端代码中；用户自定义扩展通过 `skills/` 目录注册。
- **Plan 中不存在 `skill` 类型 Step**。用户 Skill 在规划阶段被 Planner 分析后，**直接展开为对 `exec_cmd` 内置工具的调用**。
- 后端支持 **SSE 流式输出**，输出内容区分 thinking、tool_invoke、llm 等不同类型。
- Planner 的**规划过程**与 Executor 的**执行过程**拆分为独立接口，同时提供封装好的统一接口。
- Step 执行上下文使用 `contextvars` 封装，避免层层传参，天然支持并发隔离。

---

## 2. 目录结构

```
project-root/
├── agent/                  # 后端代码
│   ├── __init__.py
│   ├── config.py           # 配置读取（config.yaml）
│   ├── api.py              # HTTP 接口层（plan / execute / run，SSE 流式输出）
│   ├── router.py           # 入口分类器（Quick Reply / Planning）
│   ├── planner.py          # 规划器：意图理解 → Plan JSON
│   ├── executor.py         # 执行器：顺序执行 Step，SSE 事件推送
│   ├── registry.py         # Skill 注册中心（管理 skills/user/ 目录）
│   ├── models/             # 多模型封装
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── deepseek.py
│   │   ├── gemini.py
│   │   └── qwen.py
│   └── tools/              # 内置工具实现（直接调用，不走 Registry）
│       ├── __init__.py     # 扫描并导出所有内置工具元数据
│       ├── read_file.py
│       ├── write_file.py
│       ├── str_replace.py
│       ├── exec_cmd.py     # 框架级基础命令执行能力（也执行用户 Skill 脚本）
│       ├── find.py
│       ├── oss_upload.py
│       └── tavily_search.py
├── skills/                 # 用户自定义 Skill（通过 SKILL.md 注册）
│   └── user/               # 用户上传目录
│       └── example_skill/
│           ├── SKILL.md
│           ├── exec.py     # 主入口脚本
│           └── helper.py   # 辅助脚本（skill 内部使用，Planner 不感知）
├── web/                    # 前端项目目录（后续迭代）
│   └── ...
├── config.yaml
└── README.md
```

---

## 3. 架构概述

```
User Input
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Router    │────→│   Planner   │────→│  Executor   │
│  (分类器)    │     │  (规划器)    │     │  (执行器)    │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                     │
                           │ 查询可用能力         │ 执行 tool 类型 Step
                           │                     │ （统一调用内置工具函数）
                           ▼                     ▼
              ┌──────────────────────┐    ┌─────────────┐
              │   内置 Tools 元数据    │    │  agent/tools │
              │  (agent/tools/*.py)   │    │  内置函数    │
              └──────────────────────┘    └─────────────┘
                           │
                           │ Lazy Load
                           ▼
                    ┌─────────────┐
                    │  Registry   │
                    │ (用户 Skill)│
                    │  读取:      │
                    │ read_file   │
                    └─────────────┘
```

| 组件 | 职责 |
|------|------|
| **Router** | 判断用户意图：闲聊/简单问答 vs 需工具/复杂规划 |
| **Planner** | 解析意图 → 获取所有可用能力元数据（内置 Tools + 用户 Skill） → 输出 Plan JSON。**用户 Skill 在 Plan 中直接展开为 `exec_cmd` 调用** |
| **Executor** | 按 Plan 顺序执行 Step。所有 `tool` 类型 Step 统一调用 `agent/tools/` 中的内置函数 |
| **Registry** | 管理 `skills/user/` 目录。扫描 SKILL.md Frontmatter 构建元数据索引；需要时调用 `read_file` 读取完整内容 |

**关键设计**：
- **Plan 中只有 `tool` 和 `llm` 等动作类型**。用户 Skill 不是一级执行实体，而是被 Planner "编译"成对内置工具 `exec_cmd` 的调用。
- Executor 的逻辑非常纯粹：看到 `tool` 类型，根据 `tool_id` 找到对应内置函数执行即可。不需要感知 "这是用户 Skill"。
- 如果有多个脚本文件，那是 skill 内部的事——SKILL.md 中的 `execution_script` 只指定一个主入口，主入口负责调度内部其他脚本。

---

## 4. 内置工具（Builtin Tools）

`agent/tools/` 目录下，每个工具一个 Python 模块。模块内嵌 `META` 元数据字典 + `execute(**kwargs)` 函数。

| Tool ID | 名称 | 用途 | 关键参数 |
|---------|------|------|----------|
| `read_file` | 读取文件 | 读取指定路径文本文件内容 | `path`, `offset`, `n_lines` |
| `write_file` | 写入文件 | 创建新文件或覆盖已有文件 | `path`, `content`, `mode` |
| `str_replace` | 文本替换 | 在文件中进行字符串替换 | `path`, `old`, `new`, `replace_all` |
| `exec_cmd` | 命令执行 | 执行 Shell 命令（**也用于执行用户 Skill 脚本**） | `command`, `args`（dict 或 list）, `description`, `timeout`, `background` |
| `find` | 查找 | 按文件名模式或内容搜索文件 | `pattern`, `path`, `glob`, `type` |
| `oss_upload` | 对象存储上传 | 上传本地文件到对象存储 | `local_path`, `remote_key` |
| `tavily_search` | Tavily 搜索 | 通过 Tavily API 搜索网络信息 | `query`, `max_results` |

**特殊说明**：
- `exec_cmd` 是框架级基础能力：执行 shell 命令、也执行用户 Skill 脚本。
- `oss_upload` 依赖 `config.yaml` 中的 `oss` 段。
- `tavily_search` 依赖 `config.yaml` 中的 `search` 段（Tavily API Key）。
- 所有内置工具统一接口：`META = {...}` + `def execute(**kwargs) -> dict:`。

---

## 5. 用户自定义 Skill

`skills/user/` 目录下，每个 Skill 一个子目录，包含 `SKILL.md` 和执行脚本。

```markdown
---
skill_id: my_skill
name: 我的自定义技能
description: 这是一个用户上传的自定义技能
type: skill
---

## 参数定义

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| input | string | 是 | 输入内容 |

## 执行方式

execution_script: "exec.py"
# 如果有多个脚本文件，exec.py 是主入口，其他脚本由 exec.py 内部调用
```

- Registry 初始扫描时，仅解析 YAML Frontmatter，缓存 `skill_id` → `{name, description, type}`。
- Planner 确定需要该 Skill 后，Registry 调用内置 `read_file` 读取完整 `SKILL.md`，获取 `params_schema` 与 `execution_script`。
- **Planner 直接生成 `exec_cmd` 调用**。Planner 根据 `execution_script` 构造基础命令，业务参数通过 `args` 字典传入。
- 示例 Plan：
  ```json
  {"type": "tool", "tool_id": "exec_cmd", "params": {"command": "python3 skills/user/my_skill/exec.py", "args": {"input": "xxx"}}}
  ```
- `exec_cmd` 内部将 `args` 字典自动拼接为 `--key value` 格式（或列表按位置拼接），并用 `shlex.quote()` 做 shell 转义。
- 如果 skill 有多个脚本文件，`execution_script` 指定唯一主入口，其他文件由主入口自行调度。Planner 和 Executor 都不关心 skill 内部有几个文件。

---

## 6. Skill 渐进式批露（Lazy Loading）

**仅针对用户自定义 Skill**：

1. **初始加载**：Registry 扫描 `skills/user/`，只读取每个 `SKILL.md` 的 YAML Frontmatter（`skill_id`、`name`、`description`），构建轻量索引。
2. **Planner 决策**：Planner 合并「内置 Tools 元数据」+「Registry 用户 Skill 元数据」作为可用能力列表，进行规划。
3. **按需加载**：Planner 发现需要某用户 Skill，通过 `registry.lazy_load(skill_id)` 读取完整 `SKILL.md`。
4. **Plan 生成**：Planner 将用户 Skill 调用**直接展开为 `exec_cmd` 的 `tool` 类型 Step**。

**内置工具无需 Lazy Loading**：元数据直接内嵌在 Python 模块中，运行时直接读取。

---

## 7. Step 类型

**取消 `skill` 类型**。所有"动作"统一为 `tool` 类型，由 `tool_id` 区分具体能力。

| 类型 | 用途 | 关键字段 |
|------|------|----------|
| `tool` | 调用内置工具 | `tool_id`（如 `read_file`、`exec_cmd`、`tavily_search`） |
| `llm` | LLM 直接生成/推理 | `prompt` |
| `user_input` | 暂停执行，向用户提问或确认 | `question`, `options` |
| `store_state` | 将中间结果存入命名变量 | `key`, `value` |

**Plan JSON 示例**：

```json
{
  "plan": [
    {
      "step_id": 1,
      "type": "tool",
      "tool_id": "tavily_search",
      "params": { "query": "轻量级 Agent 框架" }
    },
    {
      "step_id": 2,
      "type": "tool",
      "tool_id": "read_file",
      "params": { "path": "README.md" }
    },
    {
      "step_id": 3,
      "type": "tool",
      "tool_id": "exec_cmd",
      "params": {
        "command": "python skills/user/my_custom_skill/exec.py",
        "stdin": "{\"input\": \"{{step_1.output}}\"}"
      }
    },
    {
      "step_id": 4,
      "type": "llm",
      "prompt": "总结以下内容：{{step_2.output}}"
    }
  ],
  "context_passing": "sequential"
}
```

---

## 8. 工作模式

| 模式 | 触发条件 | 执行路径 | 目的 |
|------|----------|----------|------|
| **Quick Reply** | 闲聊、问候、简单 Q&A | Router → 直接调用 LLM 流式回复，**跳过 Planner + Executor** | 省 Token、响应快 |
| **Planning** | 需工具、多步骤、复杂任务 | Router → Planner → Executor → SSE 流式输出 | 处理复杂逻辑 |

**Router（分类器）**：
- 位于系统入口，接收用户输入后第一时间执行。
- 可通过轻量规则或一次轻量 LLM 调用实现。
- 支持用户手动干预和切换模式。

---

## 9. 模型配置

支持多厂商模型，在 `config.yaml` 中统一声明：

```yaml
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
```

---

## 10. 配置文件规范（config.yaml）

```yaml
agent:
  name: "lightweight-agent"
  skill_dir: "./skills/user"
  default_mode: "auto"         # auto | quick_reply | planning

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

oss:
  provider: "aliyun"
  endpoint: "https://oss-cn-hangzhou.aliyuncs.com"
  bucket: "my-bucket"
  access_key_id: "${OSS_ACCESS_KEY_ID}"
  access_key_secret: "${OSS_ACCESS_KEY_SECRET}"
```

---

## 11. SSE 流式输出格式

后端通过 **Server-Sent Events (SSE)** 向前端推送执行过程的各类事件。每个事件为一段 JSON 数据。

### 11.1 事件类型定义

| 事件类型 (`type`) | 说明 | 典型字段 |
|-------------------|------|----------|
| `thinking` | 思考过程/中间推理 | `content` |
| `plan_generated` | Planner 完成规划 | `plan` (JSON 数组) |
| `tool_invoke` | 开始调用内置工具 | `step_id`, `tool_id`, `params` |
| `tool_result` | 内置工具执行完成 | `step_id`, `tool_id`, `result` |
| `llm` | LLM 生成的文本片段（流式） | `step_id`, `content` |
| `user_input_request` | 需要用户输入 | `step_id`, `question`, `options` |
| `error` | 执行错误 | `step_id`, `message`, `strategy` |
| `done` | 全部完成 | `final_result` |

**注意**：由于 Plan 中用户 Skill 也表现为 `tool` 类型（`tool_id: "exec_cmd"`），因此其调用和结果通过 `tool_invoke` / `tool_result` 事件输出。前端可通过 `params.command` 中的路径区分具体执行的是哪个用户 Skill。

### 11.2 示例 SSE 流

```
data: {"type": "thinking", "content": "用户要求搜索并总结，需要进入 Planning 模式"}

data: {"type": "plan_generated", "plan": [{"step_id": 1, "type": "tool", "tool_id": "tavily_search", ...}, ...]}

data: {"type": "tool_invoke", "step_id": 1, "tool_id": "tavily_search", "params": {"query": "轻量级 Agent 框架"}}

data: {"type": "tool_result", "step_id": 1, "tool_id": "tavily_search", "result": "..."}

data: {"type": "tool_invoke", "step_id": 3, "tool_id": "exec_cmd", "params": {"command": "python skills/user/my_custom_skill/exec.py", "stdin": "..."}}

data: {"type": "tool_result", "step_id": 3, "tool_id": "exec_cmd", "result": "..."}

data: {"type": "llm", "step_id": 4, "content": "根据搜索结果"}
data: {"type": "llm", "step_id": 4, "content": "，轻量级 Agent 框架主要有以下特点"}

data: {"type": "done", "final_result": "根据搜索结果，轻量级 Agent 框架..."}
```

---

## 12. API 接口设计

提供 **三个独立接口**：规划、执行、以及封装好的统一运行接口。

### 12.1 `POST /api/plan` —— 仅规划

**用途**：调试 Planner，查看生成的 Plan JSON，不执行。

**请求**：
```json
{
  "input": "帮我搜索轻量级 Agent 框架并总结",
  "mode": "planning"
}
```

**响应**（普通 JSON）：
```json
{
  "plan": [
    {"step_id": 1, "type": "tool", "tool_id": "tavily_search", "params": {"query": "轻量级 Agent 框架"}},
    {"step_id": 2, "type": "tool", "tool_id": "read_file", "params": {"path": "README.md"}},
    {"step_id": 3, "type": "tool", "tool_id": "exec_cmd", "params": {"command": "python3 skills/user/my_custom_skill/exec.py", "args": {"input": "{{step_1.output}}"}}},
    {"step_id": 4, "type": "llm", "prompt": "总结：{{step_2.output}}"}
  ]
}
```

### 12.2 `POST /api/execute` —— 仅执行

**用途**：传入已有的 Plan JSON，由 Executor 顺序执行并 SSE 流式输出。

**请求**：
```json
{
  "plan": [...],
  "context": {}  // 可选：注入初始上下文
}
```

**响应**：`Content-Type: text/event-stream`，SSE 流（见第 11 节）。

### 12.3 `POST /api/run` —— 封装接口（plan + execute）

**用途**：实际生产使用。先自动规划，再立即执行，全过程 SSE 流式输出。

**请求**：
```json
{
  "input": "帮我搜索轻量级 Agent 框架并总结",
  "mode": "auto"  // auto | quick_reply | planning
}
```

**响应**：`Content-Type: text/event-stream`

```
data: {"type": "thinking", "content": "进入 Planning 模式..."}
data: {"type": "plan_generated", "plan": [...]}
data: {"type": "tool_invoke", "step_id": 1, ...}
...
data: {"type": "done", "final_result": "..."}
```

**Quick Reply 模式下**：
```
data: {"type": "thinking", "content": "进入 Quick Reply 模式"}
data: {"type": "llm", "content": "你好"}
data: {"type": "done", "final_result": "你好！有什么可以帮你的吗？"}
```

---

## 13. ExecutionContext 设计

Step 执行上下文使用 `contextvars` 封装，避免在工具函数间层层传递 `context` 参数。

```python
class ExecutionContext:
    _ctx = contextvars.ContextVar("agent_ctx", default=None)
    
    def __init__(self):
        self.outputs = {}      # step_id -> output
        self.variables = {}    # store_state 存储的变量
    
    @classmethod
    def get_current(cls):
        return cls._ctx.get()
    
    def set_output(self, step_id, output):
        self.outputs[str(step_id)] = output
    
    def resolve(self, template: str) -> str:
        # 解析 {{step_N.output}} 和 ${var_name}
        ...
```

**执行流程**：
1. Executor 创建 `ExecutionContext` 并绑定到当前 contextvar
2. 执行 Step 前，调用 `ctx.resolve()` 解析模板参数
3. 执行 Step 后，调用 `ctx.set_output()` 写入结果
4. 工具函数内部如需访问上下文，通过 `ExecutionContext.get_current()` 读取

**优势**：
- 无需在每个工具函数签名中加 `context` 参数
- 天然支持并发隔离（每个 async task / thread 有自己的 contextvar）
- 日志可自动附加当前 step_id 等执行状态

---

## 14. Token 效率设计要点

1. **用户 Skill 渐进式批露**：Registry 初始只加载 name + description，选中后才读取完整 SKILL.md。
2. **内置工具元数据内嵌**：无需文件 IO，运行时直接读取，零额外 Token 开销。
3. **Plan 类型统一**：所有动作统一为 `tool` 类型，Executor 无需分支判断。
4. **Quick Reply 模式**：简单任务跳过完整的 Planner + Executor 流程。
5. **精确上下文引用**：使用 `{{step_N.output}}` 按需引用，避免全量上下文拷贝。
6. **最小化 Plan JSON**：Plan 只包含必要参数，不加冗余注释或解释。
7. **轻量 Router**：分类器使用最短的判断逻辑，减少前置 LLM 调用开销。

---

## 15. 实现计划

### Phase 1: 后端基础框架（MVP）

- [ ] 建立项目目录结构：`agent/`、`skills/user/`
- [ ] 实现配置读取模块（`config.yaml` 解析，支持环境变量）
- [ ] 实现多模型封装（`agent/models/`，支持 deepseek / gemini / qwen）
- [ ] 实现 **7 个内置工具**（`agent/tools/`）
  - `read_file`, `write_file`, `str_replace`, `exec_cmd`, `find`, `oss_upload`, `tavily_search`
  - 每个工具模块包含 `META` 元数据 + `execute()` 函数
  - `tools/__init__.py` 自动扫描并导出所有内置工具
- [ ] 实现 **Registry** 模块（仅管理 `skills/user/`）
  - Skill 目录扫描、YAML Frontmatter 元数据解析与索引
  - Lazy Load 接口：调用内置 `read_file` 读取完整 SKILL.md
- [ ] 实现 **Planner** 模块
  - LLM 调用封装（支持多模型切换）
  - 合并「内置 Tools 元数据」+「Registry 用户 Skill 元数据」作为可用能力列表
  - Plan JSON 生成：**所有动作统一为 `tool` 类型**（用户 Skill 直接展开为 `tool_id: "exec_cmd"` 的调用）
  - 用户 Skill 按需加载集成
- [ ] 实现 **Executor** 模块
  - 顺序执行引擎
  - 所有 `tool` 类型 Step 统一路由到 `agent/tools/` 中的内置函数
  - 上下文传递（`{{step_N.output}}` 解析与替换）
  - **ExecutionContext**：使用 `contextvars.ContextVar` 封装执行上下文，存储 `step_id → output` 映射和 `store_state` 变量。工具函数可通过 `ExecutionContext.get_current()` 隐式读取当前执行状态，无需显式传参
  - 错误处理：retry / skip / fail
- [ ] 实现 **Router / 分类器**
  - Quick Reply vs Planning 判断逻辑
  - 用户模式切换支持
- [ ] 实现 **API 层**（`agent/api.py`）
  - `POST /api/plan` —— 仅规划，返回 Plan JSON
  - `POST /api/execute` —— 仅执行，SSE 流式输出
  - `POST /api/run` —— 封装接口（plan + execute），SSE 流式输出
  - SSE 事件封装：thinking / plan_generated / tool_invoke / tool_result / llm / error / done
- [ ] 端到端集成测试
  - 内置工具链路测试（如 tavily_search → read_file → llm 总结）
  - 用户 Skill 懒加载链路测试（Plan 中应直接展开为 `exec_cmd` 调用）
  - SSE 流式输出格式验证

### Phase 2: 扩展与完善

- [ ] 实现 `user_input` Step 类型（任务中途暂停交互）
- [ ] 实现 `store_state` Step 类型（显式变量存储与引用）
- [ ] Registry 支持运行时热加载（用户上传新 Skill 后无需重启）
- [ ] 错误处理策略细化：重试间隔、最大重试次数、失败回退
- [ ] Router 自动判断阈值与算法调优

### Phase 3: 前端与稳定性（后续迭代）

- [ ] Plan 持久化 / 断点恢复 / 状态保存
- [ ] `web/` 前端项目基础框架搭建
- [ ] 前端 SSE 流式接收与多类型内容渲染（thinking / tool_invoke / llm 等）
- [ ] Registry Skill 版本管理（多版本共存与回滚）
