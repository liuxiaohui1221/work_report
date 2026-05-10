#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化周报生成脚本（团队版）
功能：整合本地规划文件 + 团队成员Git提交记录和代码变更，按人按项目生成周报。
使用前：
1. 安装依赖：pip install openai requests openpyxl python-dotenv anthropic
2. 修改 config.py 中的团队成员配置
3. 修改 prompts 目录下的 md 文件可自定义 prompt
4. 运行：python weekly_report.py
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
    PLAN_DATA_DIR, PLATFORM_DIR, AGENT_DIR,
    MAX_DIFF_LINES, MODEL_NAME, MAX_TOKENS, TEMPERATURE,
    TEAM_MEMBERS, TEAM_MEMBER_SOURCE, DEFAULT_ROLE
)

# Prompt 文件路径
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts")
PERSONAL_WEEKLY_PROMPT_FILE = os.path.join(PROMPTS_DIR, "personal_weekly_prompt.md")
PROJECT_WEEKLY_PROMPT_FILE = os.path.join(PROMPTS_DIR, "project_weekly_prompt.md")

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


def get_git_commits_with_hash(repo_path: str) -> str:
    """获取指定 Git 仓库的本周提交记录（包含完整hash用于追溯）"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    since = monday.strftime("%Y-%m-%d")
    until = sunday.strftime("%Y-%m-%d")

    cmd = [
        "git", "-C", repo_path, "log",
        f"--since={since}", f"--until={until}",
        "--pretty=format:%H | %s | %an | %ad",
        "--date=short"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        print(f"git repo_path:{repo_path},git result:{result}")
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
            if not lines:
                return "本周无提交记录"
            # 格式化输出，每行包含 hash、提交信息、作者、日期
            formatted = []
            for line in lines:
                parts = line.split(" | ", 3)
                if len(parts) == 4:
                    commit_hash = parts[0][:12]  # 只取前12位
                    message = parts[1]
                    author = parts[2]
                    date = parts[3]
                    formatted.append(f"- [{commit_hash}] {message} ({author}, {date})")
                else:
                    formatted.append(line)
            return "\n".join(formatted)
        return f"获取Git日志失败: {result.stderr}"
    except FileNotFoundError:
        return "错误: 请确认已安装Git并加入PATH"
    except Exception as e:
        return f"执行Git命令异常: {e}"


def get_git_commits_with_hash_for_author(repo_path: str, author_name: str, author_email: str) -> str:
    """获取指定仓库本周本人的提交记录（包含完整hash用于追溯）"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    since = monday.strftime("%Y-%m-%d")
    until = sunday.strftime("%Y-%m-%d")

    # 尝试用name过滤
    cmd = [
        "git", "-C", repo_path, "log",
        f"--since={since}", f"--until={until}",
        f"--author={author_name}",
        "--pretty=format:%H | %s | %an | %ad",
        "--date=short"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            formatted = []
            for line in lines:
                parts = line.split(" | ", 3)
                if len(parts) == 4:
                    commit_hash = parts[0][:12]
                    message = parts[1]
                    author = parts[2]
                    date = parts[3]
                    formatted.append(f"- [{commit_hash}] {message} ({author}, {date})")
                else:
                    formatted.append(line)
            return "\n".join(formatted) if formatted else "本周无提交记录"
        # 如果name没结果，尝试email
        cmd[-3] = f"--author={author_email}"
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            formatted = []
            for line in lines:
                parts = line.split(" | ", 3)
                if len(parts) == 4:
                    commit_hash = parts[0][:12]
                    message = parts[1]
                    author = parts[2]
                    date = parts[3]
                    formatted.append(f"- [{commit_hash}] {message} ({author}, {date})")
                else:
                    formatted.append(line)
            return "\n".join(formatted) if formatted else "本周无提交记录"
        return "本周无提交记录"
    except Exception as e:
        return f"获取Git提交记录异常: {e}"


def get_git_commits(repo_path: str) -> str:
    """获取指定 Git 仓库的本周提交记录（全部作者）"""
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


def get_git_authors(repo_path: str) -> list:
    """获取本周/今日Git提交中的所有唯一作者信息"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    since = monday.strftime("%Y-%m-%d")
    until = sunday.strftime("%Y-%m-%d")

    cmd = [
        "git", "-C", repo_path, "log",
        f"--since={since}", f"--until={until}",
        "--pretty=format:%an|%ae|%an",  # name|email|username
        "--date=short"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
            # 去重：按 name|email 组合唯一
            authors = {}
            for line in lines:
                parts = line.split("|")
                if len(parts) >= 3:
                    name, email, username = parts[0], parts[1], parts[2]
                    key = f"{name}|{email}"
                    if key not in authors:
                        authors[key] = {"name": name, "email": email, "git_name": username}
            return list(authors.values())
        return []
    except Exception as e:
        print(f"获取Git作者异常: {e}")
        return []


def get_git_diff(repo_path: str, author: str = None, max_lines: int = MAX_DIFF_LINES) -> str:
    """获取本周的代码变更（patch diff）"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    since = monday.strftime("%Y-%m-%d")
    until = sunday.strftime("%Y-%m-%d")

    cmd = [
        "git", "-C", repo_path, "log",
        f"--since={since}", f"--until={until}",
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
                return "本周无代码变更"
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


def get_repo_path_for_project(project: str) -> str:
    """获取项目对应的仓库路径"""
    if project == PLATFORM_DIR:
        return PROJECT1_REPO_PATH
    elif project == AGENT_DIR:
        return PROJECT2_REPO_PATH
    return None


def get_project_name(project: str) -> str:
    """获取项目显示名称"""
    if project == PLATFORM_DIR:
        return PROJECT1_NAME
    elif project == AGENT_DIR:
        return PROJECT2_NAME
    return project


def generate_personal_context(member: dict, all_members: list) -> str:
    """生成个人周报上下文"""
    plan_files = {}
    git_commits = {}
    personal_diffs = {}
    personal_commits_with_hash = {}
    project_role_map = member["project_roles"]

    for project in project_role_map.keys():
        plan_files[project] = read_local_plan_files(project)
        repo_path = get_repo_path_for_project(project)
        git_commits[project] = get_git_commits(repo_path)
        # 获取本人的提交记录（含hash用于追溯）
        personal_commits_with_hash[project] = get_git_commits_with_hash_for_author(repo_path, member["git_name"], member["email"])

        diff = get_git_diff(repo_path, author=member["git_name"])
        if diff.startswith("本周无代码变更") or diff.startswith("获取Git diff失败"):
            diff_email = get_git_diff(repo_path, author=member["email"])
            if not diff_email.startswith("获取Git diff失败"):
                diff = diff_email
        personal_diffs[project] = diff

    plan_parts = []
    for project in project_role_map.keys():
        plan_parts.append(f"**{get_project_name(project)}（{project}目录）**\n{plan_files[project]}")

    commit_parts = []
    diff_parts = []
    for project in project_role_map.keys():
        commit_parts.append(f"**{get_project_name(project)}**\n{git_commits[project]}")
        diff_parts.append(f"**{get_project_name(project)}**\n{personal_diffs[project]}")

    # 收集所有角色用于prompt
    all_roles = set()
    for roles_str in project_role_map.values():
        for r in roles_str.split(","):
            all_roles.add(r.strip())

    # 本人提交记录（含hash）用于追溯
    personal_commit_parts = []
    for project in project_role_map.keys():
        personal_commit_parts.append(f"**{get_project_name(project)}**\n{personal_commits_with_hash[project]}")

    context = f"""### 项目规划（本地文件）
{chr(10).join(plan_parts)}

### 本周 Git 提交记录（全部成员）

{chr(10).join(commit_parts)}

### 本人本周提交记录（含提交号，用于追溯）

{chr(10).join(personal_commit_parts)}

### 本人本周代码变更 (Diff)

{chr(10).join(diff_parts)}

人员信息：{member['name']}，Git用户名：{member['git_name']}，邮箱：{member['email']}"""
    return context, ",".join(all_roles)


def generate_project_context(project: str, all_members: list) -> str:
    """生成项目周报上下文"""
    repo_path = get_repo_path_for_project(project)
    all_commits = get_git_commits(repo_path)
    plan_text = read_local_plan_files(project)

    member_diffs = []
    for member in all_members:
        if project in member["project_roles"]:
            diff = get_git_diff(repo_path, author=member["git_name"])
            if diff.startswith("本周无代码变更") or diff.startswith("获取Git diff失败"):
                diff_email = get_git_diff(repo_path, author=member["email"])
                if not diff_email.startswith("获取Git diff失败"):
                    diff = diff_email
            roles_str = member["project_roles"][project]
            role_display = get_roles_display(roles_str)
            member_diffs.append(f"**{member['name']}（{role_display}）**\n{diff}")

    context = f"""### 项目：{get_project_name(project)}

### 项目规划（{project}目录）
{plan_text}

### 本周 Git 提交记录（全部成员）
{all_commits}

### 各成员代码变更
{chr(10).join(member_diffs)}

项目角色说明：team_leader=团队负责人, developer=开发人员, architecture=架构师"""
    return context


def generate_report(context: str, prompt_file: str, **format_kwargs) -> str:
    """调用大模型生成报告"""
    client = anthropic.Anthropic(
        base_url=MINIMAX_BASE_URL,
        api_key=MINIMAX_API_KEY,
    )

    prompt_template = load_prompt_file(prompt_file)
    system_prompt = prompt_template.format(**format_kwargs)

    response = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": [{"type": "text", "text": context}]}],
        temperature=TEMPERATURE,
    )

    text_blocks = [block.text for block in response.content if block.type == "text"]
    return "\n".join(text_blocks)


def get_role_display(role: str) -> str:
    """获取单个角色中文显示"""
    role_map = {
        "team_leader": "团队负责人",
        "developer": "开发人员",
        "architecture": "架构师"
    }
    return role_map.get(role, role)


def get_roles_display(roles_str: str) -> str:
    """获取多个角色中文显示（逗号分隔）"""
    roles = [r.strip() for r in roles_str.split(",")]
    displays = [get_role_display(r) for r in roles]
    return "、".join(displays)


def discover_team_members_from_git() -> list:
    """从Git提交记录自动发现团队成员"""
    # 收集所有项目的作者
    all_authors = {}
    repo_map = {PLATFORM_DIR: PROJECT1_REPO_PATH, AGENT_DIR: PROJECT2_REPO_PATH}

    for project, repo_path in repo_map.items():
        authors = get_git_authors(repo_path)
        for author in authors:
            key = f"{author['name']}|{author['email']}"
            if key not in all_authors:
                all_authors[key] = {
                    "name": author["name"],
                    "git_name": author["git_name"],
                    "email": author["email"],
                    "project_roles": {}
                }
            # 该作者在这个项目有提交
            if project not in all_authors[key]["project_roles"]:
                all_authors[key]["project_roles"][project] = DEFAULT_ROLE

    return list(all_authors.values())


def get_team_members() -> list:
    """获取团队成员列表，根据配置决定来源"""
    if TEAM_MEMBER_SOURCE == "git":
        members = discover_team_members_from_git()
        print(f"[INFO] 从Git自动发现 {len(members)} 名成员")
        return members
    else:
        return TEAM_MEMBERS


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print(f">>> 正在提取本周数据并调用 {MODEL_NAME} 生成周报...\n")

    today = datetime.now()
    year_month = today.strftime("%Y%m")
    monday = today - timedelta(days=today.weekday())
    week_folder = monday.strftime("%Y%m%d")
    date_str = today.strftime("%Y-%m-%d")

    # 输出目录结构：output/YYYYMM/YYYYMMDD/
    output_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output", year_month, week_folder)
    person_output_dir = os.path.join(output_base, "by_person")
    project_output_dir = os.path.join(output_base, "by_project")
    os.makedirs(person_output_dir, exist_ok=True)
    os.makedirs(project_output_dir, exist_ok=True)

    # 获取团队成员（根据配置决定来源）
    team_members = get_team_members()

    # 1. 生成个人周报
    print("=== 生成个人周报 ===")
    for member in team_members:
        ctx, roles_str = generate_personal_context(member, team_members)
        role_display = get_roles_display(roles_str)
        print(f"--- 为 {member['name']}（{role_display}）生成周报 ---")
        report = generate_report(
            ctx,
            PERSONAL_WEEKLY_PROMPT_FILE,
            MY_NAME=member['name'],
            MY_ROLE=role_display,
            MY_GIT_NAME=member['git_name'],
            MY_EMAIL=member['email']
        )
        filepath = os.path.join(person_output_dir, f"{member['name']}_周报_{date_str}.md")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[OK] {member['name']} 周报已保存")

    # 2. 生成项目周报
    print("\n=== 生成项目周报 ===")
    for project in [PLATFORM_DIR, AGENT_DIR]:
        print(f"--- 为 {get_project_name(project)} 生成周报 ---")
        ctx = generate_project_context(project, team_members)
        report = generate_report(
            ctx,
            PROJECT_WEEKLY_PROMPT_FILE,
            PROJECT_NAME=get_project_name(project),
            PROJECT_DIR=project
        )
        filepath = os.path.join(project_output_dir, f"{get_project_name(project)}_周报_{date_str}.md")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[OK] {get_project_name(project)} 周报已保存")

    print(f"\n[INFO] 输出目录: {output_base}")
    print(f"[INFO] 个人周报: {person_output_dir}")
    print(f"[INFO] 项目周报: {project_output_dir}")