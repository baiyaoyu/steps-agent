# 输出与存储指南

## 本地保存

默认保存到工作目录的 `tmp_files/` 下，保持工作目录整洁：
- 封面图片：`./tmp_files/`（如 `tmp_files/cover.jpg`）
- MD 文件：`./tmp_files/`（如 `tmp_files/news_2024-01-15.md`）

## 上传到对象存储

推荐使用 `oss-uploader` Skill，默认路径：
- 封面图片：`--path news_covers/`
- MD 文件：`--path news_docs/`

示例：
```bash
# 上传封面图片
python oss-uploader/scripts/upload.py cover.jpg --bucket my-bucket --path news_covers/

# 上传 MD 文件
python oss-uploader/scripts/upload.py news.md --bucket my-bucket --path news_docs/
```

## PDF 导出

使用 `markdown-to-pdf` Skill 转换后再上传，默认 PDF 上传路径：`news_pdfs/`
