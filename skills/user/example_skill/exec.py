#!/usr/bin/env python3
import sys
import json

# 从命令行参数读取 JSON（--input 格式）
# 实际由 exec_cmd 传入 --input "xxx"
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
args = parser.parse_args()

result = {"message": f"示例技能处理完成: {args.input}"}
print(json.dumps(result, ensure_ascii=False))
