---
name: news-aggregator
description: 聚合联合早报、澎湃新闻、财新网、36氪生成24h/48h/72h新闻时间线，智能挑选热点新闻生成封面，支持获取36氪"8点1氪"专栏并解析内容结构；当用户需要查看新闻时间线、追踪近期热点、获取今日8点1氪、快速了解时事动态时使用
dependency:
  python:
    - requests==2.31.0
    - beautifulsoup4==4.12.2
    - lxml==4.9.3
    - python-dotenv>=1.0.0
---

# 新闻聚合器

## 任务目标
- 从联合早报（中国版面）、澎湃新闻、财新网、36氪获取最新资讯
- 生成 24h/48h/72h 新闻时间线
- 智能挑选热点/重要新闻生成封面图片
- 一次性完整输出美观的时间线

## 环境配置

### 代理配置（可选）
联合早报可能需要翻墙访问，参考 [`.env.example`](.env.example) 创建 `.env` 文件：

```bash
# .env 文件内容
ZAOBAO_PROXY=http://127.0.0.1:7890
```

其他新闻源（澎湃、财新、36氪）在国内可直接访问，无需代理。

其他新闻源（澎湃、财新、36氪）在国内可直接访问，无需代理。

## 操作步骤

### 1. 获取新闻数据
调用脚本获取新闻：
```bash
python scripts/news_fetcher.py --hours 24 --source all --limit 20 --cover crawl
```

**参数说明**：
- `--hours`：时间范围，可选 4、8、12、24（默认）、48、72 小时
- `--source`：新闻来源
  - `all`：全部来源（默认）
  - `zaobao`：仅联合早报
  - `pengpai`：仅澎湃新闻
  - `caixin`：仅财新网
  - `kr36`：仅36氪
  - 可逗号分隔多个：`zaobao,pengpai,caixin`
- `--limit`：最大新闻条数，0表示不限制（默认0）
- `--cover`：封面模式
  - `crawl`：爬取新闻原图（默认，节约 token）
  - `ai`：AI 生成封面图片
- `--8d1k`：只获取36氪"8点1氪"专栏内容，不获取普通新闻

**多来源均衡**：当 `--source all` 时，使用 `--limit` 会均衡分配各来源的新闻数量，确保"雨露均沾"。

脚本输出包含以下字段：
- `generated_at`：文档生成时间（格式：YYYY-MM-DD HH:MM:SS）
- `hours`：时间范围
- `source`：当前使用的新闻来源
- `limit`：设置的最大条数
- `cover_mode`：封面模式
- `news`：新闻列表（按时间降序）
- `timeline`：按日期分组的时间线数据
- `hotspot`：热点新闻及封面信息
- `source_counts`：各来源新闻数量统计

### 2. 封面图片处理

**封面模式**（`--cover` 参数）：
- `crawl`（默认）：从新闻详情页爬取原图，节约 token
- `ai`：使用智能体视觉模型根据标题生成封面图片

**爬取模式（crawl）**：
- 脚本自动从热点新闻详情页提取封面图片URL
- 输出 `hotspot.cover_image` 字段包含图片URL
- 若爬取失败，`cover_mode` 返回 `crawl_failed`

**AI生成模式（ai）**：
- 智能体使用视觉模型生成封面
- 提示词模板：`生成一张新闻封面图片，主题为"[新闻标题]"，风格专业简洁，适合新闻报道`

**热点识别标准**（脚本已处理）：
- 标题含关键词：制裁、访华、会议、政策、突破、首次等
- 来源权威性优先
- 时间最新优先

### 3. 输出时间线

按以下格式一次性输出：

```markdown
# 新闻时间线

> 近 24 小时资讯汇总 | 来源：联合早报、澎湃新闻、财新、36氪

---

![封面](封面图片URL)
### 热点新闻
**热点标题**
*来源 | 时间*

---

## 2024-01-15

| 时间 | 来源 | 标题 |
|:----:|:----:|:-----|
| 12:30 | 联合早报 | [新闻标题](链接) |
| 10:50 | 澎湃新闻 | [新闻标题](链接) |
| 09:30 | 财新 | [新闻标题](链接) [会员] |
| 08:15 | 36氪 | [新闻标题](链接) |

## 2024-01-14

| 时间 | 来源 | 标题 |
|:----:|:----:|:-----|
| 23:45 | 联合早报 | [新闻标题](链接) |

---

**统计**：共 X 条 | 联合早报 X 条 | 澎湃新闻 X 条 | 财新 X 条 | 36氪 X 条
```

**输出流程**：

**Step 1: 标题与元信息**
- 标题：`# 新闻时间线`
- 描述：`> 近 X 小时资讯汇总 | 来源：...`

**Step 2: 热点封面区**（若有封面）
- 封面图片：`![封面](hotspot.cover_image)`
- 热点标题：`### 热点新闻`
- 来源时间：`*hotspot.source | hotspot.time*`
- 若 `cover_mode` 为 `crawl_failed`，跳过封面图片，仅展示标题

**Step 3: 时间线表格**（按日期分组）
- 日期标题：`## YYYY-MM-DD`
- 表格格式：时间居中、来源居中、标题左对齐
- 同一日新闻按时间降序排列
- 财新付费文章标注 `[会员]` 或 `[限时免费]`

**Step 4: 统计信息**
- 格式：`**统计**：共 X 条 | 联合早报 X 条 | 澎湃新闻 X 条 | 财新 X 条 | 36氪 X 条`

## 新闻来源说明

| 来源 | 定位 | 特点 |
|------|------|------|
| 联合早报 | 综合时政 | 国际视角，新加坡媒体 |
| 澎湃新闻 | 综合时政 | 国内视角，深度报道 |
| 财新 | 财经深度 | 部分付费，专业财经 |
| 36氪 | 科技创投 | 科技创业，投融资动态 |

**财新付费标识**：
- `is_free: true` - 免费文章
- `is_free: false` - 付费文章（标注 `[会员]`）
- `free_duration` - 限时免费（如"7天免费"）

## 资源索引
- 配置示例：[.env.example](.env.example)
- 新闻爬取脚本：[scripts/news_fetcher.py](scripts/news_fetcher.py)
- 爬取器基类：[scripts/fetchers/base.py](scripts/fetchers/base.py)
- 联合早报爬取器：[scripts/fetchers/zaobao.py](scripts/fetchers/zaobao.py)
- 澎湃新闻爬取器：[scripts/fetchers/pengpai.py](scripts/fetchers/pengpai.py)
- 财新爬取器：[scripts/fetchers/caixin.py](scripts/fetchers/caixin.py)
- 36氪爬取器：[scripts/fetchers/kr36.py](scripts/fetchers/kr36.py)
- 数据源配置：[references/sources.md](references/sources.md)
- 输出与存储指南：[references/output-guide.md](references/output-guide.md)

## 扩展功能

### 获取"8点1氪"专栏
36氪每日发布的"8点1氪"专栏文章，汇总当日科技圈要闻，适合快速了解晨间资讯。

**获取今日专栏**：
```bash
python scripts/news_fetcher.py --8d1k
```

**专栏触发场景**：
- 用户说"获取今日8点1氪"、"看下8点1氪"、"今天的8点1氪"
- 用户想快速了解36氪精选的科技动态

**专栏内容结构**：
脚本已解析专栏文章的层级结构，返回格式如下：
```json
{
  "daily_digest": {
    "column_type": "8点1氪",
    "title": "8点1氪丨甲骨文裁员3万人；市监局回应...",
    "time": "04月02日 08:00",
    "url": "https://36kr.com/p/3748927500387072",
    "sections": [
      {
        "section_title": "TOP 3大新闻",
        "items": [
          {"title": "甲骨文裁员3万人", "content": "具体内容..."},
          {"title": "市监局回应张雪机车", "content": "具体内容..."}
        ]
      },
      {
        "section_title": "大公司/大事件",
        "items": [...]
      }
    ]
  }
}
```

**智能体处理建议**：
- 专栏已按板块分组，每个板块包含多条新闻（title + content）
- 可根据板块重要性选择性展示（如"TOP 3大新闻"优先）
- 每条新闻已拆分标题和内容，无需再解析
- 所有新闻共用一个原文链接，在末尾统一展示

**专栏输出格式示例**：
```markdown
## 8点1氪 | 2024-01-15

> 来源：36氪 | 发布时间：08:00

### TOP 3大新闻

**甲骨文裁员3万人**

全球软件巨头甲骨文凌晨向员工群发邮件，宣布启动大规模裁员...

**市监局回应张雪机车**

公司预售车型因禁止新手购买被投诉...

### 大公司/大事件

**宇树科技被抽中现场检查**

中国证券业协会发布抽查名单...

**原特斯拉中国高管入职小米**

孔艳双将负责汽车销售工作...

---
> [查看原文](https://36kr.com/p/3748927500387072)
```

**注意**：
- 所有子新闻共用专栏原文链接，不单独配链接
- 若当日无专栏文章，返回 `daily_digest: null`

### 上传封面图片
当封面图片存在防盗链问题时，可使用对象存储服务解决。
推荐使用 **oss-uploader** Skill 完成上传。

### 导出时间线为 PDF
可将 Markdown 时间线导出为 PDF 文件。
推荐使用 **markdown-to-pdf** Skill 完成转换。

## 注意事项
- **Token 优化**：紧凑 JSON 输出，仅必要字段；默认爬取原图，无需图像生成
- 支持时间范围：4h、8h、12h、24h（默认）、48h、72h
- 使用 `--limit` 限制新闻条数，多来源时自动均衡分配
- 封面模式：`crawl` 爬取原图（默认），`ai` AI 生成
- 网络超时已内置处理
- 财新付费文章会标注 `[会员]`

## 使用示例

**场景 1：快速浏览 4h 内新闻**
```bash
python scripts/news_fetcher.py --hours 4 --source all
```

**场景 2：限制 10 条新闻（多来源均衡）**
```bash
python scripts/news_fetcher.py --hours 24 --source all --limit 10
```

**场景 3：仅财新和36氪**
```bash
python scripts/news_fetcher.py --source caixin,kr36
```

**场景 4：仅联合早报 20 条**
```bash
python scripts/news_fetcher.py --source zaobao --limit 20
```

**场景 5：AI 生成封面图片**
```bash
python scripts/news_fetcher.py --hours 24 --source all --cover ai
```

**场景 6：仅获取"8点1氪"专栏**
```bash
python scripts/news_fetcher.py --8d1k
```

**场景 7：获取新闻同时展示专栏**
```bash
python scripts/news_fetcher.py --hours 24 --source all
# 输出会包含 daily_digest 字段（如果有专栏文章）
```
