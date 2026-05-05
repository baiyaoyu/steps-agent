# 轻量动态智能体设计方案

> 基于前期讨论整理 · 2026-04-26

---

## 核心动机

DeerFlow + LangGraph 对简单任务来说太"重"了，固定开销（overhead）明显。需要一个更轻量的动态智能体系统来替代传统 workflow，对简单任务做到 token 高效。

---

## 整体架构：三组件模型

```
┌─────────────────────────────────────────────────┐
│                   User Input                      │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  ① Planner (LLM-based 规划器)                      │
│  - 将用户输入解析为步骤序列                        │
│  - 输出结构化 JSON Plan                            │
│  - 包含 Skill 元数据分析/加载                       │
│  - 步骤类型: tool / llm / conditional / loop       │
└────────────────────┬─────────────────────────────┘
                     │ Plan JSON
                     ▼
┌──────────────────────────────────────────────────┐
│  ② Executor (顺序执行器)                           │
│  - 按 Plan 顺序执行步骤                            │
│  - 执行具体脚本/代码                                │
│  - 错误处理 + 重试                                  │
│  - 上下文传递                                       │
└────────────────────┬─────────────────────────────┘
                     │ 执行结果
                     ▼
┌──────────────────────────────────────────────────┐
│  ③ Registry (动态注册中心)                         │
│  - Tool/Skill 动态注册                              │
│  - 热加载 (hot-loading)                             │
│  - 版本管理                                         │
│  - 元数据索引                                       │
└──────────────────────────────────────────────────┘
```

---

## 组件详解

### 1. Planner

- **输入**：用户自然语言请求
- **职责**：
  - 解析用户意图
  - 从 Registry 查询可用 Skill/Tool 元数据
  - 编排步骤序列，输出结构化 Plan JSON
  - Skill 分析放在 Planner 侧，决定"用什么"
- **输出格式**：

```json
{
  "plan": [
    {
      "step_id": 1,
      "type": "tool",
      "skill": "web_search",
      "params": {
        "query": "轻量级 AI Agent 框架对比"
      },
      "description": "搜索相关资料"
    },
    {
      "step_id": 2,
      "type": "llm",
      "prompt_template": "基于以下内容生成摘要：{{step_1.output}}",
      "description": "生成摘要"
    },
    {
      "step_id": 3,
      "type": "conditional",
      "condition": "step_2.output 长度 < 100",
      "branches": {
        "true": { "step_id": 4, "type": "tool", "skill": "web_search", "params": { "query": "补充搜索" } },
        "false": { "step_id": 5, "type": "llm", "prompt_template": "格式化输出" }
      },
      "description": "判断摘要是否需要补充"
    },
    {
      "step_id": 6,
      "type": "loop",
      "max_iterations": 3,
      "steps": [
        { "step_id": 6.1, "type": "tool", "skill": "read_file", "params": {} },
        { "step_id": 6.2, "type": "llm", "prompt_template": "分析内容" }
      ],
      "description": "逐文件分析"
    }
  ],
  "context_passing": "sequential"
}
```

### 2. Executor

- **输入**：Plan JSON
- **职责**：
  - 严格按顺序执行 Plan 中的步骤
  - 调用具体 Skill 的执行脚本（Executor 只负责"怎么执行"，不关心"用什么"）
  - 步骤间上下文传递（前一步输出作为后一步输入）
  - 错误处理：步骤失败时决定重试还是跳过
  - 支持 conditional 分支跳转和 loop 迭代
- **关键设计**：
  - Executor 不包含 Skill 分析逻辑 —— 纯粹的执行引擎
  - 每个步骤执行结果写入上下文字段，可通过 `{{step_N.output}}` 引用
  - 错误策略：retry(N) / skip / fail

### 3. Registry

- **职责**：
  - 管理所有可用 Tool/Skill 的注册信息
  - 提供元数据索引（名称、描述、参数 schema、版本）
  - 支持热加载：运行时动态添加/卸载 Skill
  - 版本管理：支持多版本共存和回滚
- **元数据 Schema 示例**：

```json
{
  "skill_id": "web_search",
  "version": "2.1.0",
  "description": "搜索引擎查询",
  "type": "tool",
  "params_schema": {
    "query": { "type": "string", "required": true },
    "max_results": { "type": "integer", "default": 5 }
  },
  "execution_script": "/skills/web_search/exec.sh",
  "hot_loadable": true
}
```

---

## 步骤类型定义

| 类型 | 说明 | 示例 |
|------|------|------|
| `tool` | 执行工具/技能调用 | `web_search`, `read_file` |
| `llm` | LLM 文本处理 | 摘要、翻译、格式化 |
| `conditional` | 条件分支 | if/else 逻辑判断 |
| `loop` | 循环迭代 | 逐文件分析、批量处理 |

---

## 工作模式：Quick Reply vs. Planning

系统支持两种工作模式，避免简单任务也被进入完整规划流程（浪费 token）：

| 模式 | 适用场景 | 行为 |
|------|---------|------|
| **Quick Reply** | 简单问候、Q&A、闲聊 | 不经过 Planner，直接 LLM 回复 |
| **Planning** | 复杂任务、多步骤操作 | 完整 Planner → Executor 流程 |

**模式选择方式**：
1. **手动选择**：用户明确指定模式
2. **自动判断**：系统根据输入特征（长度、复杂度、是否含工具关键词）自动决策

---

## Skill 分析职责划分（关键决策）

经过讨论，最终的职责划分方案：

| 职责 | 归属 | 原因 |
|------|------|------|
| **Skill 元数据分析**（"用什么"） | **Planner** | Planner 需要知道可用什么工具才能规划步骤 |
| **Skill 执行脚本**（"怎么执行"） | **Executor** | Executor 负责调用具体执行代码，不关心分析逻辑 |

这样划分的理由：
- Planner 做意图理解和步骤编排时，必须了解有哪些 Skill 可用（元数据是规划的输入）
- Executor 是纯执行引擎，不需要知道 Skill 的来源和选择逻辑
- 职责分离清晰，Planner 可以换、Executor 也可以换

---

## Token 效率设计要点

1. **Plan JSON 结构化输出**：替代完整自然语言 Prompt 链，减少 token 消耗
2. **Quick Reply 模式**：简单任务跳过规划流程
3. **上下文引用 `{{step_N.output}}`**：精确传递而非完整上下文拷贝
4. **Registry 元数据查询**：按需加载 Skill 描述，而非全部注入
5. **最小化输出**：Plan 只包含必要参数，不加注释/解释

---

## 后续可讨论的方向

- Executor 是否需要支持并行步骤执行（DAG 模式）？
- Plan 持久化 / 断点恢复 / 状态保存
- 与 LangGraph 的兼容层（能否用这个轻量设计驱动 LangGraph backend？）
- 错误处理策略的详细设计（重试间隔、回退策略、人工介入点）
- Quick Reply / Planning 的自动判断阈值和算法
