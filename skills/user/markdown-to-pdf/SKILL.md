---
name: markdown-to-pdf
description: 将Markdown转换为PDF文档，支持中文、表格、图片等复杂格式，可选用WeasyPrint或pdfkit引擎；当用户需要导出PDF报告、转换文档格式时使用
dependency:
  python:
    - markdown>=3.4.0
    - weasyprint>=60.0
  system:
    - apt-get update && apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info fonts-noto-cjk fonts-noto-color-emoji
---

# Markdown 转 PDF 转换器

## 任务目标
- 将 Markdown 内容转换为 PDF 文档
- 支持中文、表格、图片、代码块等复杂格式
- 提供专业排版的 PDF 输出

## 操作步骤

### 1. 从文件转换

```bash
python scripts/convert.py input.md -o output.pdf
```

### 2. 从标准输入转换

```bash
cat input.md | python scripts/convert.py - -o output.pdf
```

### 3. 指定文档标题

```bash
python scripts/convert.py input.md -o output.pdf --title "报告标题"
```

**参数说明**：
- `input`：输入 Markdown 文件路径（`-` 表示从标准输入读取）
- `-o, --output`：输出 PDF 文件路径（可选，默认同名 `.pdf`）
- `--title, -t`：文档标题（默认"新闻时间线"）
- `--css`：自定义 CSS 文件路径
- `--output-json`：以 JSON 格式输出结果

### 4. 输出格式

**默认输出**：
```
PDF 已生成: /path/to/output.pdf
```

**JSON 输出**（`--output-json`）：
```json
{
  "success": true,
  "pdf_path": "/path/to/output.pdf"
}
```

## PDF 样式特性

| 特性 | 说明 |
|------|------|
| 页面尺寸 | A4 |
| 字体 | 思源黑体（Noto Sans CJK SC） |
| 表格 | 带边框、隔行变色 |
| 图片 | 自适应宽度、居中 |
| 代码块 | 灰色背景、等宽字体 |
| 链接 | 蓝色、无下划线 |

## 文件存储指南

### 本地保存
- 默认输出到 `./tmp_files/` 目录，保持工作目录整洁
- 或通过 `-o` 参数指定其他路径

### 上传到对象存储
推荐使用 `oss-uploader` Skill，默认路径：`--path news_pdfs/`

示例：
```bash
python oss-uploader/scripts/upload.py output.pdf --bucket my-bucket --path news_pdfs/
```

## 注意事项
- 系统依赖包含中文字体和 Emoji 字体
- WeasyPrint 为默认引擎，pdfkit 为备选
- 复杂表格和图片会自动处理

## 资源索引
- 转换脚本：[scripts/convert.py](scripts/convert.py)
