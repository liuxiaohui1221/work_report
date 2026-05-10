#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化日报生成脚本
功能：整合本地规划文件 + 当天Git提交记录和代码变更，通过 MiniMax M2.7 生成日报。
使用前：
1. 安装依赖：pip install openai requests openpyxl python-dotenv anthropic
2. 修改 config.py 中的配置信息
3. 修改 prompts/daily_report_prompt.md 可自定义 prompt
4. 运行：python daily_report.py
"""

import os
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv
import anthropic
import openpyxl
from config import (
    PROJECT1_NAME, PROJECT1_REPO_PATH,
    PROJECT2_NAME, PROJECT2_REPO_PATH, PROJECT2_PHASE, CURRENT_PHASE,
    PLAN_DATA_DIR, PLATFORM_DIR, AGENT_DIR,
    MY_GIT_NAME, MY_EXCEL_NAME, MY_EMAIL,
    MAX_DIFF_LINES, MODEL_NAME, MAX_TOKENS, TEMPERATURE
)

# Prompt 文件路径
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts")
DAILY_REPORT_PROMPT_FILE = os.path.join(PROMPTS_DIR, "daily_report_prompt.md")

load_dotenv()

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/anthropic")


def load_prompt_file(filepath: str) -> str:
    """从md文件加载prompt内容"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return f"错误: Prompt文件未找到: {filepath}"
    except Exception as e:
        return f"错误: 读取Prompt文件失败: {e}"


def get_today_commits(repo_path: str) -> str:
    """获取指定 Git 仓库的当天提交记录（全部作者）"""
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    cmd = [
        "git", "-C", repo_path, "log",
        f"--since={today}", f"--until={tomorrow}",
        "--pretty=format:%h - %s (%an, %ad %H:%M)",
        "--date=short"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        print(f"git repo_path:{repo_path},git result:{result}")
        if result.returncode == 0:
            return result.stdout.strip() or "今日无提交记录"
        return f"获取Git日志失败: {result.stderr}"
    except FileNotFoundError:
        return "错误: 请确认已安装Git并加入PATH"
    except Exception as e:
        return f"执行Git命令异常: {e}"


def get_today_diff(repo_path: str, author: str = None, max_lines: int = MAX_DIFF_LINES) -> str:
    """获取当天的代码变更（patch diff）"""
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    cmd = [
        "git", "-C", repo_path, "log",
        f"--since={today}", f"--until={tomorrow}",
        "--patch",
        "--pretty=format:",
    ]

    if author:
        cmd.insert(2, f"--author={author}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            diff = result.stdout.strip()
            if not diff:
                return "今日无代码变更"
            lines = diff.split('\n')
            if len(lines) > max_lines:
                return "\n".join(lines[:max_lines]) + "\n... (diff 内容过长，已截断，仅显示前 {} 行)".format(max_lines)
            return diff
        return f"获取Git diff失败: {result.stderr}"
    except Exception as e:
        return f"执行Git diff命令异常: {e}"


def read_local_plan_files(project: str = None) -> str:
    """从本地读取 Excel 或 Markdown 规划文件，合并为文本"""
    base_dir = PLAN_DATA_DIR
    if project:
        base_dir = os.path.join(PLAN_DATA_DIR, project)

    if base_dir and os.path.isdir(base_dir):
        files = []
        for f in os.listdir(base_dir):
            if f.endswith('.xlsx') or f.endswith('.md'):
                files.append(os.path.join(base_dir, f))
        if not files:
            return f"（未在 {project or '根目录'} 下找到任何 .xlsx 或 .md 文件）"
    else:
        return f"（未配置规划文件路径，请设置 PLAN_DATA_DIR）"

    content_parts = []
    for filepath in files:
        filename = os.path.basename(filepath)
        if filepath.endswith('.xlsx'):
            try:
                wb = openpyxl.load_workbook(filepath, data_only=True)
                sheet = wb.active
                lines = []
                for row in sheet.iter_rows(values_only=True):
                    row_str = "\t".join([str(c) if c is not None else "" for c in row])
                    lines.append(row_str)
                content_parts.append(f"### 文件: {filename} (Excel)\n" + "\n".join(lines))
            except Exception as e:
                content_parts.append(f"### 文件: {filename} (Excel) 读取失败: {e}")
        elif filepath.endswith('.md'):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    md_content = f.read()
                content_parts.append(f"### 文件: {filename} (Markdown)\n{md_content}")
            except Exception as e:
                content_parts.append(f"### 文件: {filename} (Markdown) 读取失败: {e}")

    return "\n\n".join(content_parts)


def get_daily_context() -> str:
    """整合数据源，生成日报上下文"""
    git_project1 = get_today_commits(PROJECT1_REPO_PATH)
    git_project2 = get_today_commits(PROJECT2_REPO_PATH)

    author_name = MY_GIT_NAME
    author_email = MY_EMAIL
    diff1 = get_today_diff(PROJECT1_REPO_PATH, author=author_name)
    diff2 = get_today_diff(PROJECT2_REPO_PATH, author=author_name)

    if diff1.startswith("今日无代码变更") or diff1.startswith("获取Git diff失败"):
        diff1_email = get_today_diff(PROJECT1_REPO_PATH, author=author_email)
        if not diff1_email.startswith("获取Git diff失败"):
            diff1 = diff1_email
    if diff2.startswith("今日无代码变更") or diff2.startswith("获取Git diff失败"):
        diff2_email = get_today_diff(PROJECT2_REPO_PATH, author=author_email)
        if not diff2_email.startswith("获取Git diff失败"):
            diff2 = diff2_email

    plan_platform = read_local_plan_files(PLATFORM_DIR)
    plan_agent = read_local_plan_files(AGENT_DIR)

    today = datetime.now().strftime("%Y-%m-%d")

    context = f"""日期：{today}

### 项目规划（本地文件）

**平台项目（{PLATFORM_DIR}目录）**
{plan_platform}

**Agent项目（{AGENT_DIR}目录）**
{plan_agent}

### 今日 Git 提交记录

**项目: {PROJECT1_NAME}**
{git_project1}

**项目: {PROJECT2_NAME}（{CURRENT_PHASE}）**
{git_project2}

### 今日本人代码变更 (Diff)

**{PROJECT1_NAME}**
{diff1}

**{PROJECT2_NAME}**
{diff2}

要求：
- {PROJECT1_NAME} 只统计本人工作产出
- {PROJECT2_NAME} 是本人负责的项目，需体现负责人视角
请结合提交记录和代码变更，准确描述具体完成的技术工作。"""
    return context


def generate_report(context: str) -> str:
    """调用大模型生成日报"""
    client = anthropic.Anthropic(
        base_url=MINIMAX_BASE_URL,
        api_key=MINIMAX_API_KEY,
    )

    prompt_template = load_prompt_file(DAILY_REPORT_PROMPT_FILE)
    system_prompt = prompt_template.format(
        MY_EXCEL_NAME=MY_EXCEL_NAME,
        MY_GIT_NAME=MY_GIT_NAME,
        MY_EMAIL=MY_EMAIL
    )

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": [{"type": "text", "text": context}]}],
        temperature=TEMPERATURE,
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    return "\n".join(text_blocks)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print(f">>> 正在提取今日数据并调用 {MODEL_NAME} 生成日报...\n")
    ctx = get_daily_context()

    today = datetime.now()
    year_month = today.strftime("%Y%m")
    date_str = today.strftime("%Y-%m-%d")
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output", year_month)
    os.makedirs(output_dir, exist_ok=True)

    print("--- 生成日报 ---")
    report = generate_report(ctx)

    with open(os.path.join(output_dir, f"日报_{date_str}.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[OK] 日报已保存: {os.path.join(output_dir, f'日报_{date_str}.md')}")