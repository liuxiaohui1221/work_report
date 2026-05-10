#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化周报生成脚本（Agent项目负责人视角）
功能：整合本地规划文件（Excel/Markdown）+ 两个Git仓库的周提交记录，通过 MiniMax M2.7 生成结构化周报。
使用前：
1. 安装依赖：pip install openai requests openpyxl python-dotenv
2. 修改 config.py 中的配置信息
3. 运行：python weekly_report.py
"""

import os
import subprocess
from datetime import datetime, timedelta
from dotenv import load_dotenv
import anthropic
import openpyxl
from config import (
    PROJECT1_NAME, PROJECT1_REPO_PATH, PROJECT1_PHASE,
    PROJECT2_NAME, PROJECT2_REPO_PATH, PROJECT2_PHASE, CURRENT_PHASE,
    PLAN_DATA_DIR, MY_GIT_NAME, MY_EXCEL_NAME, MY_EMAIL
)

load_dotenv()

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/anthropic")


def get_git_commits(repo_path: str) -> str:
    """获取指定 Git 仓库的本周提交记录"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    since = monday.strftime("%Y-%m-%d")
    until = sunday.strftime("%Y-%m-%d")

    cmd = [
        "git", "-C", repo_path, "log",
        f"--since={since}", f"--until={until}",
        "--pretty=format:%h - %s (%an, %ad)",
        "--date=short"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        print(f"git repo_path:{repo_path},git result:{result}")
        if result.returncode == 0:
            return result.stdout.strip() or "本周无提交记录"
        return f"获取Git日志失败: {result.stderr}"
    except FileNotFoundError:
        return "错误: 请确认已安装Git并加入PATH"
    except Exception as e:
        return f"执行Git命令异常: {e}"


def read_local_plan_files() -> str:
    """从本地读取 Excel 或 Markdown 规划文件，合并为文本"""
    if PLAN_DATA_DIR and os.path.isdir(PLAN_DATA_DIR):
        files = []
        for f in os.listdir(PLAN_DATA_DIR):
            if f.endswith('.xlsx') or f.endswith('.md'):
                files.append(os.path.join(PLAN_DATA_DIR, f))
        if not files:
            return "（未在指定目录下找到任何 .xlsx 或 .md 文件）"
    else:
        return "（未配置规划文件路径，请设置 PLAN_DATA_DIR）"

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


def get_weekly_context() -> str:
    """整合所有数据源，生成 AI 输入上下文"""
    git_project1 = get_git_commits(PROJECT1_REPO_PATH)
    git_project2 = get_git_commits(PROJECT2_REPO_PATH)
    plan_text = read_local_plan_files()

    context = f"""### 项目规划（本地文件）
{plan_text}

### 本周 Git 提交记录

**项目: {PROJECT1_NAME}（{PROJECT1_PHASE}）**
{git_project1}

**项目: {PROJECT2_NAME}， {CURRENT_PHASE}（{PROJECT2_PHASE}）**
{git_project2}

注意：{PROJECT2_NAME} 是用户本人负责的项目，汇报时需体现负责人视角。"""
    return context


def generate_report(context: str) -> str:
    """调用 MiniMax M2.7 模型生成周报（向上级汇报）"""
    client = anthropic.Anthropic(
        base_url=MINIMAX_BASE_URL,
        api_key=MINIMAX_API_KEY,
    )

    system_prompt = f"""你是一个技术项目负责人的周报撰写助手。请根据提供的项目规划和本周Git提交记录，生成符合钉钉周报模板的结构化周报。

## 关键要求
本周完成工作只统计本人({MY_EXCEL_NAME})的Git提交记录，Git用户名：{MY_GIT_NAME}，邮箱：{MY_EMAIL}。
所有工作项必须来自本人的实际工作产出，不要混入他人的工作内容。

## 钉钉周报模板结构

### 1. 本周完成工作
- 简洁列出已完成工作，突出核心产出
- 按客户项目分段落（招商局、中石油等）
- Agent项目分阶段描述

### 2. 本周工作总结
- 一句话概括整体进展 + 状态灯（🟢🟡🔴）
- 量化产出/里程碑
- 风险与卡点（如有）

### 3. 下周工作计划
- 按客户项目列出
- 承诺式表达，明确交付成果

### 4. 需协调与帮助
- 列出需协调事项及原因

## 要求
1. 严格按4段结构输出
2. 语言简洁，避免流水账
3. 主动暴露风险和阻塞点
4. 输出纯Markdown"""

    response = client.messages.create(
        model="MiniMax-M2.7",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": [{"type": "text", "text": context}]}],
        temperature=0.5,
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    return "\n".join(text_blocks)


def generate_agent_project_report(context: str) -> str:
    """调用 MiniMax M2.7 模型生成Agent项目群周报"""
    client = anthropic.Anthropic(
        base_url=MINIMAX_BASE_URL,
        api_key=MINIMAX_API_KEY,
    )

    system_prompt = """你是一个技术项目负责人，负责向Agent项目群汇报项目整体进展。请根据提供的项目规划和本周Git提交记录，生成面向项目团队的结构化周报。

## 关键要求
本周完成工作应反映Agent项目的整体进度和团队贡献，不限于本人。
作为项目负责人，需站在全局视角汇报整体健康度和里程碑进展。

## 汇报结构

### 1. 本周完成工作
- 简洁列出已完成工作，突出核心产出
- 按客户项目分段落（招商局、中石油等）
- Agent项目分阶段描述整体进展

### 2. 本周工作总结
- 一句话概括整体进展 + 状态灯（🟢🟡🔴）
- 当前阶段标注
- 关键成果与风险问题

### 3. 下周工作计划
- 按客户项目列出
- 承诺式表达，明确交付成果

### 4. 需协调与帮助
- 列出需协调事项及原因

## 要求
1. 严格按4段结构输出
2. 体现全局把控能力
3. 主动暴露风险和阻塞点
4. 输出纯Markdown"""

    response = client.messages.create(
        model="MiniMax-M2.7",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": [{"type": "text", "text": context}]}],
        temperature=0.5,
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    return "\n".join(text_blocks)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print(">>> 正在提取本周数据并调用 MiniMax M2.7 生成周报...\n")
    ctx = get_weekly_context()

    today = datetime.now()
    year_month = today.strftime("%Y%m")
    monday = today - timedelta(days=today.weekday())
    week_folder = monday.strftime("%Y%m%d")
    date_str = today.strftime("%Y-%m-%d")
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output", year_month, week_folder)
    os.makedirs(output_dir, exist_ok=True)

    # 生成钉钉周报
    print("--- 生成钉钉周报 ---")
    report = generate_report(ctx)

    with open(os.path.join(output_dir, f"周报_{date_str}.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print("[OK] 钉钉周报已保存")

    # 生成Agent项目群周报
    print("--- 生成Agent项目群周报 ---")
    agent_report = generate_agent_project_report(ctx)

    with open(os.path.join(output_dir, f"Agent项目群周报_{date_str}.md"), "w", encoding="utf-8") as f:
        f.write(agent_report)
    print("[OK] Agent项目群周报已保存")

    print(f"\n[INFO] 输出目录: {output_dir}")
    print(f"[INFO] 包含文件: .md 共2个文件")