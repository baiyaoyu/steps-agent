#!/usr/bin/env python3
"""
Markdown 转 PDF 转换器

支持功能：
- 将 Markdown 内容或文件转换为 PDF
- 支持中文、图片、表格等复杂格式
- 可选上传到对象存储

使用方式：
    # 从文件转换
    python convert.py input.md -o output.pdf
    
    # 从标准输入转换
    echo "# 标题" | python convert.py - -o output.pdf
    
    # 转换并上传到 OSS
    python convert.py input.md -o output.pdf --upload

依赖安装：
    pip install markdown weasyprint
    # 或者使用 pdfkit（需要安装 wkhtmltopdf）
    pip install pdfkit
"""

import os
import sys
import argparse
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

# 尝试导入依赖
try:
    import markdown
    from markdown.extensions.tables import TableExtension
    from markdown.extensions.fenced_code import FencedCodeExtension
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

try:
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

try:
    import pdfkit
    PDFKIT_AVAILABLE = True
except ImportError:
    PDFKIT_AVAILABLE = False


# 默认 CSS 样式
DEFAULT_CSS = """
@page {
    size: A4;
    margin: 2cm;
}

body {
    font-family: "Noto Sans CJK SC", "Source Han Sans CN", "Microsoft YaHei", 
                 "PingFang SC", "Hiragino Sans GB", sans-serif;
    font-size: 12pt;
    line-height: 1.6;
    color: #333;
}

h1 {
    font-size: 24pt;
    color: #1a1a1a;
    border-bottom: 2px solid #333;
    padding-bottom: 10px;
    margin-bottom: 20px;
}

h2 {
    font-size: 18pt;
    color: #2a2a2a;
    border-bottom: 1px solid #666;
    padding-bottom: 5px;
    margin-top: 25px;
}

h3 {
    font-size: 14pt;
    color: #3a3a3a;
    margin-top: 20px;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 15px 0;
    font-size: 10pt;
}

th, td {
    border: 1px solid #ddd;
    padding: 8px 12px;
    text-align: left;
}

th {
    background-color: #f5f5f5;
    font-weight: bold;
}

tr:nth-child(even) {
    background-color: #fafafa;
}

a {
    color: #0066cc;
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

img {
    max-width: 100%;
    height: auto;
    margin: 10px 0;
}

blockquote {
    border-left: 4px solid #ddd;
    margin: 15px 0;
    padding: 10px 20px;
    background-color: #f9f9f9;
    color: #666;
}

code {
    background-color: #f4f4f4;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: "Consolas", "Monaco", monospace;
    font-size: 10pt;
}

pre {
    background-color: #f4f4f4;
    padding: 15px;
    border-radius: 5px;
    overflow-x: auto;
    font-size: 9pt;
}

hr {
    border: none;
    border-top: 1px solid #ddd;
    margin: 20px 0;
}

/* 时间线特殊样式 */
.timeline-header {
    text-align: center;
    margin-bottom: 30px;
}

.cover-image {
    display: block;
    max-width: 80%;
    margin: 20px auto;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}

.hotspot-section {
    background-color: #fff9e6;
    border: 1px solid #ffcc00;
    border-radius: 8px;
    padding: 15px;
    margin: 20px 0;
}

.statistics {
    text-align: center;
    font-size: 11pt;
    color: #666;
    margin-top: 30px;
    padding-top: 15px;
    border-top: 1px solid #ddd;
}
"""


class MarkdownToPDF:
    """Markdown 转 PDF 转换器"""
    
    def __init__(self, css: Optional[str] = None):
        """
        初始化转换器
        
        Args:
            css: 自定义 CSS 样式，None 则使用默认样式
        """
        self.css = css or DEFAULT_CSS
        self._check_dependencies()
    
    def _check_dependencies(self):
        """检查依赖是否安装"""
        if not MARKDOWN_AVAILABLE:
            raise ImportError(
                "markdown 库未安装，请运行: pip install markdown"
            )
        
        if not WEASYPRINT_AVAILABLE and not PDFKIT_AVAILABLE:
            raise ImportError(
                "需要安装 weasyprint 或 pdfkit:\n"
                "  pip install weasyprint\n"
                "  或\n"
                "  pip install pdfkit (需要先安装 wkhtmltopdf)"
            )
    
    def convert(self, md_content: str, output_path: str, title: str = "新闻时间线") -> Tuple[bool, str]:
        """
        将 Markdown 内容转换为 PDF
        
        Args:
            md_content: Markdown 内容
            output_path: 输出 PDF 文件路径
            title: 文档标题
            
        Returns:
            (成功标志, PDF 路径 或 错误信息)
        """
        try:
            # 转换 Markdown 为 HTML
            html_content = self._markdown_to_html(md_content, title)
            
            # 转换 HTML 为 PDF
            return self._html_to_pdf(html_content, output_path)
            
        except Exception as e:
            return False, f"转换失败: {str(e)}"
    
    def convert_file(self, md_path: str, output_path: Optional[str] = None) -> Tuple[bool, str]:
        """
        将 Markdown 文件转换为 PDF
        
        Args:
            md_path: Markdown 文件路径
            output_path: 输出 PDF 文件路径，None 则自动生成
            
        Returns:
            (成功标志, PDF 路径 或 错误信息)
        """
        # 检查文件是否存在
        if not os.path.exists(md_path):
            return False, f"文件不存在: {md_path}"
        
        # 读取 Markdown 内容
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                md_content = f.read()
        except Exception as e:
            return False, f"读取文件失败: {str(e)}"
        
        # 生成输出路径
        if output_path is None:
            output_path = str(Path(md_path).with_suffix('.pdf'))
        
        # 提取标题（从第一个 # 标题）
        title = "新闻时间线"
        for line in md_content.split('\n'):
            if line.startswith('# '):
                title = line[2:].strip()
                break
        
        return self.convert(md_content, output_path, title)
    
    def _markdown_to_html(self, md_content: str, title: str = "新闻时间线") -> str:
        """
        将 Markdown 内容转换为 HTML
        
        Args:
            md_content: Markdown 内容
            title: 文档标题
            
        Returns:
            HTML 内容
        """
        # 配置 Markdown 扩展
        extensions = [
            'tables',
            'fenced_code',
            'nl2br',           # 换行转 <br>
            'sane_lists',      # 更好的列表处理
        ]
        
        # 转换 Markdown
        md = markdown.Markdown(extensions=extensions)
        body_html = md.convert(md_content)
        
        # 构建完整 HTML
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        {self.css}
    </style>
</head>
<body>
    {body_html}
</body>
</html>"""
        
        return html
    
    def _html_to_pdf(self, html_content: str, output_path: str) -> Tuple[bool, str]:
        """
        将 HTML 内容转换为 PDF
        
        Args:
            html_content: HTML 内容
            output_path: 输出 PDF 文件路径
            
        Returns:
            (成功标志, PDF 路径 或 错误信息)
        """
        # 优先使用 WeasyPrint
        if WEASYPRINT_AVAILABLE:
            return self._html_to_pdf_weasyprint(html_content, output_path)
        # 备用 pdfkit
        elif PDFKIT_AVAILABLE:
            return self._html_to_pdf_pdfkit(html_content, output_path)
        else:
            return False, "没有可用的 PDF 转换库"
    
    def _html_to_pdf_weasyprint(self, html_content: str, output_path: str) -> Tuple[bool, str]:
        """使用 WeasyPrint 转换"""
        try:
            font_config = FontConfiguration()
            html = HTML(string=html_content)
            css = CSS(string=self.css, font_config=font_config)
            
            html.write_pdf(output_path, stylesheets=[css], font_config=font_config)
            
            return True, output_path
            
        except Exception as e:
            return False, f"WeasyPrint 转换失败: {str(e)}"
    
    def _html_to_pdf_pdfkit(self, html_content: str, output_path: str) -> Tuple[bool, str]:
        """使用 pdfkit 转换"""
        try:
            # 写入临时 HTML 文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
                f.write(html_content)
                temp_html = f.name
            
            try:
                options = {
                    'encoding': 'UTF-8',
                    'quiet': '',
                    'page-size': 'A4',
                    'margin-top': '20mm',
                    'margin-right': '20mm',
                    'margin-bottom': '20mm',
                    'margin-left': '20mm',
                }
                
                pdfkit.from_file(temp_html, output_path, options=options)
                return True, output_path
                
            finally:
                # 清理临时文件
                os.unlink(temp_html)
                
        except Exception as e:
            return False, f"pdfkit 转换失败: {str(e)}"


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='Markdown 转 PDF 转换器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 从文件转换
    python convert.py input.md -o output.pdf
    
    # 从标准输入转换
    cat input.md | python convert.py - -o output.pdf
    
    # 指定自定义 CSS
    python convert.py input.md -o output.pdf --css custom.css
        """
    )
    
    parser.add_argument('input', help='输入 Markdown 文件路径（- 表示从标准输入读取）')
    parser.add_argument('-o', '--output', help='输出 PDF 文件路径')
    parser.add_argument('--title', '-t', default='新闻时间线', help='文档标题')
    parser.add_argument('--css', help='自定义 CSS 文件路径')
    parser.add_argument('--output-json', action='store_true', help='以 JSON 格式输出结果')
    
    args = parser.parse_args()
    
    # 读取输入
    if args.input == '-':
        md_content = sys.stdin.read()
        if not args.output:
            args.output = f"timeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    else:
        if not os.path.exists(args.input):
            print(f"错误: 文件不存在: {args.input}", file=sys.stderr)
            sys.exit(1)
        
        with open(args.input, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        if not args.output:
            args.output = str(Path(args.input).with_suffix('.pdf'))
    
    # 读取自定义 CSS
    custom_css = None
    if args.css and os.path.exists(args.css):
        with open(args.css, 'r', encoding='utf-8') as f:
            custom_css = f.read()
    
    try:
        # 转换
        converter = MarkdownToPDF(css=custom_css)
        success, result = converter.convert(md_content, args.output, args.title)
        
        if not success:
            if args.output_json:
                import json
                print(json.dumps({'success': False, 'error': result}))
            else:
                print(f"错误: {result}", file=sys.stderr)
            sys.exit(1)
        
        # 输出结果
        if args.output_json:
            import json
            output = {
                'success': True,
                'pdf_path': result
            }
            print(json.dumps(output, ensure_ascii=False))
        else:
            print(f"PDF 已生成: {result}")
    
    except ImportError as e:
        print(f"依赖缺失: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"未知错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
