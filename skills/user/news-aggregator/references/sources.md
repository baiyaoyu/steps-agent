# 新闻数据源配置

## 联合早报

### 基本信息
- **名称**：联合早报
- **简称**：早报
- **官网**：https://www.zaobao.com/
- **中国版面**：https://www.zaobao.com/news/china
- **语言**：中文简体/繁体

### 数据提取说明
- **目标 URL**：`https://www.zaobao.com/news/china`
- **主要内容区域**：`.article-list` 或 `.list-item`
- **标题元素**：`a` 标签或 `h2`/`h3` 标签
- **时间元素**：`.date` 或 `.time` 或 `<time>` 标签
- **链接格式**：相对路径，需补全域名 `https://www.zaobao.com`

### 注意事项
- 网站可能有反爬机制，已设置 User-Agent
- 编码为 UTF-8
- 部分新闻时间格式为"X小时前"，需转换为绝对时间

---

## 澎湃新闻

### 基本信息
- **名称**：澎湃新闻
- **简称**：澎湃
- **官网**：https://www.thepaper.cn/
- **语言**：中文简体

### 数据提取说明
- **目标 URL**：`https://www.thepaper.cn/`
- **主要内容区域**：`.news_title` 或 `.newsitem`
- **标题元素**：`a` 标签
- **时间元素**：`.date` 或 `.time` 标签
- **链接格式**：相对路径，需补全域名 `https://www.thepaper.cn`

### 注意事项
- 首页新闻更新频繁，建议实时爬取
- 部分新闻时间格式为"X分钟前"，需转换
- 编码为 UTF-8

---

## 数据格式规范

### JSON 输出格式
```json
[
  {
    "title": "新闻标题",
    "time": "2024-01-15 14:30",
    "source": "联合早报",
    "url": "https://www.zaobao.com/news/china/story20240115-123456"
  }
]
```

### 时间格式
- 标准格式：`YYYY-MM-DD HH:MM`
- 相对时间需转换为绝对时间
- 无法解析的时间使用当前时间

### 去重规则
- 基于 URL 去重
- 同一标题的重复新闻仅保留一条
