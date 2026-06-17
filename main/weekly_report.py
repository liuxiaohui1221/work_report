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
    PROJECTS,
    PLAN_DATA_DIR,
    MAX_DIFF_LINES, MODEL_NAME, MAX_TOKENS, TEMPERATURE,
    TEAM_MEMBERS, TEAM_MEMBER_SOURCE, DEFAULT_ROLE,
    EMAIL_ENABLED, TEAM_MEMBER_SEND_EMAIL,
    PROJECT_REPORT_RECIPIENTS, DEFAULT_PROJECT_RECIPIENTS
)
from email_sender import send_personal_report_email, send_project_report_email

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


def get_week_date_range():
    """获取周报日期范围：周一发送时获取上周数据，其他日子获取本周数据"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())

    # 周一（weekday=0）发送上周周报
    if today.weekday() == 0:
        # 上周一
        start = monday - timedelta(days=7)
        end = start + timedelta(days=6)
    else:
        start = monday
        end = start + timedelta(days=6)

    print(f"[DEBUG] get_week_date_range: today={today}, weekday={today.weekday()}, start={start}, end={end}")
    return start, end


def get_git_commits_with_hash(repo_path: str) -> str:
    """获取指定 Git 仓库的本周提交记录（包含完整hash用于追溯）"""
    start, end = get_week_date_range()
    since = start.strftime("%Y-%m-%d")
    until = end.strftime("%Y-%m-%d")

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
    start, end = get_week_date_range()
    since = start.strftime("%Y-%m-%d")
    until = end.strftime("%Y-%m-%d")

    # 获取当前分支名
    try:
        branch_result = subprocess.run(
            ["git", "-C", repo_path, "branch", "--show-current"],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
    except Exception:
        current_branch = "unknown"

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
            commits = "\n".join(formatted) if formatted else "本周无提交记录"
            return f"**当前分支**: {current_branch}\n\n{commits}"
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
            commits = "\n".join(formatted) if formatted else "本周无提交记录"
            return f"**当前分支**: {current_branch}\n\n{commits}"
        print(f"[WARN] 获取Git提交记录失败 (name={author_name}, email={author_email})，可能是git author配置与预期不符")
        return f"**当前分支**: {current_branch}\n\n本周无提交记录（警告：未找到匹配的git author，可能需要检查git config user.name/user.email）"
    except Exception as e:
        print(f"[ERROR] 获取Git提交记录异常: {e}")
        return f"获取Git提交记录异常: {e}"


def get_git_commits(repo_path: str) -> str:
    """获取指定 Git 仓库的本周提交记录（全部作者）"""
    start, end = get_week_date_range()
    since = start.strftime("%Y-%m-%d")
    until = end.strftime("%Y-%m-%d")

    # 获取当前分支名
    try:
        branch_result = subprocess.run(
            ["git", "-C", repo_path, "branch", "--show-current"],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
    except Exception:
        current_branch = "unknown"

    cmd = [
        "git", "-C", repo_path, "log",
        f"--since={since}", f"--until={until}",
        "--pretty=format:%h - %s (%an, %ad)",
        "--date=short"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        print(f"[DEBUG] git commits repo={repo_path}, branch={current_branch}, since={since}, until={until}")
        if result.returncode == 0:
            commits = result.stdout.strip() or "本周无提交记录"
            return f"**当前分支**: {current_branch}\n\n{commits}"
        print(f"[ERROR] 获取Git日志失败: {result.stderr}")
        return f"获取Git日志失败: {result.stderr}"
    except FileNotFoundError:
        print(f"[ERROR] Git命令未找到，请确认已安装Git并加入PATH")
        return "错误: 请确认已安装Git并加入PATH"
    except Exception as e:
        print(f"[ERROR] 执行Git log异常: {e}")
        return f"执行Git命令异常: {e}"


def get_git_authors(repo_path: str) -> list:
    """获取本周/今日Git提交中的所有唯一作者信息"""
    start, end = get_week_date_range()
    since = start.strftime("%Y-%m-%d")
    until = end.strftime("%Y-%m-%d")

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
    start, end = get_week_date_range()
    since = start.strftime("%Y-%m-%d")
    until = end.strftime("%Y-%m-%d")

    # 获取当前分支名
    try:
        branch_result = subprocess.run(
            ["git", "-C", repo_path, "branch", "--show-current"],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
    except Exception:
        current_branch = "unknown"

    cmd = [
        "git", "-C", repo_path, "log",
        f"--since={since}", f"--until={until}",
        "--patch",
        "--pretty=format:",
    ]

    if author:
        cmd.append(f"--author={author}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        print(f"[DEBUG] git diff for repo={repo_path}, branch={current_branch}, author={author}, since={since}, until={until}, returncode={result.returncode}")
        if result.returncode == 0:
            diff = result.stdout.strip()
            if not diff:
                return f"**当前分支**: {current_branch}\n\n本周无代码变更"
            lines = diff.split('\n')
            if len(lines) > max_lines:
                return f"**当前分支**: {current_branch}\n\n" + "\n".join(lines[:max_lines]) + f"\n... (diff 内容过长，已截断，仅显示前 {max_lines} 行)"
            return f"**当前分支**: {current_branch}\n\n{diff}"
        error_msg = result.stderr.strip()
        print(f"[WARN] git diff for author={author} 执行失败: {error_msg}")
        return f"**当前分支**: {current_branch}\n\n本周无代码变更（git diff执行失败）"
    except Exception as e:
        print(f"[ERROR] 执行Git diff命令异常: {e}")
        return f"**当前分支**: {current_branch}\n\n本周无代码变更（执行异常）"


def clone_remote_for_query(remote_url: str) -> str:
    """浅克隆远程仓库用于查询（不下载大文件）"""
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="git_query_")
    try:
        subprocess.run(
            ["git", "clone", "--depth=1", "--filter=blob:limit=0", remote_url, tmpdir],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        return tmpdir
    except Exception:
        return ""


def get_remote_git_authors(remote_url: str, since: str, until: str) -> list:
    """从远程仓库获取所有分支的作者列表"""
    tmpdir = clone_remote_for_query(remote_url)
    if not tmpdir:
        return []
    cmd = [
        "git", "-C", tmpdir, "log", "--all",
        f"--since={since}", f"--until={until}",
        "--pretty=format:%an|%ae|%an",
        "--date=short"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
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
    except Exception:
        return []
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def get_remote_git_commits_all_branches(remote_url: str, since: str, until: str, author: str = None) -> str:
    """从远程仓库获取所有分支的提交记录"""
    tmpdir = clone_remote_for_query(remote_url)
    if not tmpdir:
        return "错误: 远程仓库克隆失败"
    cmd = [
        "git", "-C", tmpdir, "log", "--all",
        f"--since={since}", f"--until={until}",
        "--pretty=format:%h - %s (%an, %ad)",
        "--date=short"
    ]
    if author:
        cmd.append(f"--author={author}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            return result.stdout.strip() if result.stdout.strip() else "本周无提交记录"
        return f"获取提交记录失败: {result.stderr.strip()}"
    except Exception as e:
        return f"执行Git命令异常: {e}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def get_remote_git_diff_all_branches(remote_url: str, since: str, until: str, author: str = None, max_lines: int = MAX_DIFF_LINES) -> str:
    """从远程仓库获取所有分支的代码变更"""
    tmpdir = clone_remote_for_query(remote_url)
    if not tmpdir:
        return "错误: 远程仓库克隆失败"
    cmd = [
        "git", "-C", tmpdir, "log", "--all",
        f"--since={since}", f"--until={until}",
        "--patch", "--pretty=format:",
    ]
    if author:
        cmd.append(f"--author={author}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            diff = result.stdout.strip()
            if not diff:
                return "本周无代码变更"
            lines = diff.split('\n')
            if len(lines) > max_lines:
                return "\n".join(lines[:max_lines]) + f"\n... (diff 内容过长，已截断，仅显示前 {max_lines} 行)"
            return diff
        return f"获取diff失败: {result.stderr.strip()}"
    except Exception as e:
        return f"执行Git命令异常: {e}"
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def read_local_plan_files(project: str = None) -> str:
    """从本地读取 Excel 或 Markdown 规划文件，合并为文本"""
    base_dir = PLAN_DATA_DIR
    if project:
        project_subdir = os.path.join(PLAN_DATA_DIR, project)
        # 如果项目子目录存在，优先从子目录读取；否则从根目录读取
        if os.path.isdir(project_subdir):
            base_dir = project_subdir
        else:
            base_dir = PLAN_DATA_DIR

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


def get_gitlab_project_name(project: str) -> str:
    """从远程仓库URL中解析GitLab真实项目名称"""
    remote = PROJECTS.get(project, {}).get("remote", "")
    if not remote:
        return project
    # 取URL最后一部分（去掉.git后缀），即为项目真实名称
    name = remote.rstrip("/").split("/")[-1]
    return name.replace(".git", "")


def get_repo_path_for_project(project: str) -> str:
    """获取项目对应的仓库路径"""
    if project in PROJECTS:
        return PROJECTS[project]["local"]
    return None


def get_project_name(project: str) -> str:
    """获取项目显示名称"""
    if project in PROJECTS:
        return PROJECTS[project]["name"]
    return project


def generate_personal_context(member: dict, all_members: list) -> str:
    """生成个人周报上下文"""
    plan_files = {}
    git_commits = {}
    personal_diffs = {}
    personal_commits_with_hash = {}
    project_role_map = member["project_roles"]
    all_emails = member.get("all_emails", [member["email"]])

    for project in project_role_map.keys():
        plan_files[project] = read_local_plan_files(project)
        repo_path = get_repo_path_for_project(project)
        git_commits[project] = get_git_commits(repo_path)

        # 合并多个账号的diff和提交
        merged_diff_lines = []
        merged_commit_lines = []
        for email in all_emails:
            git_author = email
            diff = get_git_diff(repo_path, author=git_author)
            if diff and "本周无代码变更" not in diff and "（git diff执行失败）" not in diff and "（执行异常）" not in diff:
                merged_diff_lines.append(f"**[{email}]**\n{diff}")
            commits = get_git_commits_with_hash_for_author(repo_path, email, email)
            if commits and "本周无提交记录" not in commits:
                merged_commit_lines.append(f"**[{email}]**\n{commits}")

        personal_diffs[project] = "\n\n".join(merged_diff_lines) if merged_diff_lines else f"**{project}**\n本周无代码变更"
        personal_commits_with_hash[project] = "\n\n".join(merged_commit_lines) if merged_commit_lines else f"**{project}**\n本周无提交记录"

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

人员信息：{member.get('name', '')}，Git用户名：{member.get('git_name', '')}，邮箱：{member.get('email', '')}"""
    return context, ",".join(all_roles)


def generate_project_context(project: str, all_members: list) -> str:
    """生成项目周报上下文"""
    repo_path = get_repo_path_for_project(project)
    all_commits = get_git_commits(repo_path)
    plan_text = read_local_plan_files(project)

    member_diffs = []
    for member in all_members:
        if project in member["project_roles"]:
            git_author = member.get("git_name") or member.get("name") or member.get("email")
            diff = get_git_diff(repo_path, author=git_author)
            if "本周无代码变更" in diff or "（git diff执行失败）" in diff or "（执行异常）" in diff:
                diff_email = get_git_diff(repo_path, author=member.get("email"))
                if "本周无代码变更" not in diff_email and "（git diff执行失败）" not in diff_email and "（执行异常）" not in diff_email:
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


def generate_report(context: str, prompt_file: str, user_requirement: str = None, **format_kwargs) -> str:
    """调用大模型生成报告（streaming 模式，兼容 M2.7 / M3）"""
    client = anthropic.Anthropic(
        base_url=MINIMAX_BASE_URL,
        api_key=MINIMAX_API_KEY,
    )

    prompt_template = load_prompt_file(prompt_file)
    system_prompt = prompt_template.format(**format_kwargs)

    user_message = context
    if user_requirement:
        user_message = f"## 用户特殊要求\n{user_requirement}\n\n---\n\n{context}"

    with client.messages.stream(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": [{"type": "text", "text": user_message}]}],
        temperature=TEMPERATURE,
    ) as stream:
        return stream.get_final_text()


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
    repo_map = {k: v["local"] for k, v in PROJECTS.items()}

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

    try:
        print(f">>> 正在提取本周数据并调用 {MODEL_NAME} 生成周报...\n")

        today = datetime.now()
        year_month = today.strftime("%Y%m")
        # 使用 get_week_date_range() 获取正确的周开始日期
        week_start, week_end = get_week_date_range()
        week_folder = week_start.strftime("%Y%m%d")
        date_str = today.strftime("%Y-%m-%d")

        # 输出目录结构：output/YYYYMM/DD/by_person/ 和 output/YYYYMM/DD/by_project/
        output_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output", year_month, week_folder)
        person_output_dir = os.path.join(output_base, "by_person")
        project_output_dir = os.path.join(output_base, "by_project")
        os.makedirs(person_output_dir, exist_ok=True)
        os.makedirs(project_output_dir, exist_ok=True)

        # 获取团队成员（根据配置决定来源）
        team_members = get_team_members()

        # config模式下检查成员是否有代码变更，无则自动切换到git模式
        if TEAM_MEMBER_SOURCE == "config" and team_members:
            all_have_diff = True
            for member in team_members:
                has_diff = False
                for project in member.get("project_roles", {}).keys():
                    repo_path = get_repo_path_for_project(project)
                    if not repo_path:
                        continue
                    git_author = member.get("git_name") or member.get("name") or member.get("email")
                    diff = get_git_diff(repo_path, author=git_author)
                    if diff and "本周无代码变更" not in diff and "（git diff执行失败）" not in diff and "（执行异常）" not in diff:
                        has_diff = True
                        break
                    diff_email = get_git_diff(repo_path, author=member.get("email"))
                    if diff_email and "本周无代码变更" not in diff_email and "（git diff执行失败）" not in diff_email and "（执行异常）" not in diff_email:
                        has_diff = True
                        break
                if not has_diff:
                    all_have_diff = False
                    break
            if not all_have_diff:
                print("[INFO] config模式成员无代码变更，自动切换到git模式获取候选人")
                team_members = discover_team_members_from_git()
                TEAM_MEMBER_SOURCE = "git"

        # git模式下，选择要生成周报的成员并指定同一人多账号的合并关系
        if TEAM_MEMBER_SOURCE == "git" and team_members:
            # 获取git所有候选账号
            all_author_map = {}
            repo_map = {k: v["local"] for k, v in PROJECTS.items()}
            for project, repo_path in repo_map.items():
                for author in get_git_authors(repo_path):
                    all_author_map[author["email"]] = author

            # 选择账号并指定合并关系（一阶段完成）
            print("\n=== 选择汇报账号 ===")
            email_list = list(all_author_map.keys())
            for i, email in enumerate(email_list, 1):
                author = all_author_map[email]
                print(f"{i}. {author['name']} <{email}>")
            print("\n输入格式: 用逗号分隔多人的账号，空格分隔同一人多个账号")
            print("示例: 1 2, 3, 4 5 → (1+2)、(3)、(4+5) 各为一人")
            print("输入 0 → 每人单独一份周报")
            sel = input("选择: ").strip()

            if sel == "0":
                merged_members = []
                for email in email_list:
                    author = all_author_map[email]
                    merged_members.append({
                        "name": author["name"],
                        "email": author["email"],
                        "git_name": author.get("git_name", ""),
                        "all_emails": [email],
                        "project_roles": {k: DEFAULT_ROLE for k in PROJECTS}
                    })
            else:
                groups = []
                try:
                    for part in sel.split(","):
                        indices = [int(x.strip()) - 1 for x in part.split()]
                        group = [email_list[idx] for idx in indices if 0 <= idx < len(email_list)]
                        if group:
                            groups.append(group)
                except ValueError:
                    print("[WARN] 输入格式错误，默认为每人单独")
                    groups = [[e] for e in email_list]

                merged_members = []
                for group in groups:
                    primary = all_author_map[group[0]]
                    merged_members.append({
                        "name": primary["name"],
                        "email": primary["email"],
                        "git_name": primary.get("git_name", ""),
                        "all_emails": group,
                        "project_roles": {k: DEFAULT_ROLE for k in PROJECTS}
                    })

            selected_members = merged_members
            print(f"[INFO] 将为以下 {len(selected_members)} 位成员生成周报")
            for m in selected_members:
                emails_str = ", ".join(m["all_emails"])
                print(f"  - {m['name']} <{m['email']}> (账号: {emails_str})")
        else:
            selected_members = team_members

        # 检查邮件发送配置
        email_can_send = EMAIL_ENABLED and TEAM_MEMBER_SEND_EMAIL
        if not email_can_send:
            print("\n[WARNING] 邮件发送已禁用 (TEAM_MEMBER_SEND_EMAIL=False)，将跳过邮件发送")

        # 1. 检查已存在的报告文件
        existing_personal_reports = {}
        existing_project_reports = {}

        for member in selected_members:
            filepath = os.path.join(person_output_dir, f"{member['name']}_{member['email']}_周报_{date_str}.md")
            if os.path.exists(filepath):
                existing_personal_reports[member['email']] = (member, filepath)

        for project in PROJECTS:
            filepath = os.path.join(project_output_dir, f"{get_project_name(project)}_周报_{date_str}.md")
            if os.path.exists(filepath):
                existing_project_reports[project] = filepath

        # 2. 判断是使用现有报告还是重新生成
        use_existing = False
        if existing_personal_reports or existing_project_reports:
            print("=" * 60)
            print("发现已存在的周报文件")
            print("=" * 60)
            if existing_personal_reports:
                print("\n【个人周报】")
                for name, (member, path) in existing_personal_reports.items():
                    print(f"  {name}: {path}")
            if existing_project_reports:
                print("\n【项目周报】")
                for proj_name, path in existing_project_reports.items():
                    print(f"  {proj_name}: {path}")
            print("\n选择操作:")
            print("1. 使用现有报告发送邮件")
            print("2. 重新生成全部报告（覆盖现有文件）")
            choice = input("\n请输入选项 (1-2，直接回车默认使用现有报告): ").strip()
            if choice == "2":
                use_existing = False
            else:
                use_existing = True
        else:
            print("[INFO] 输出目录下没有已存在的周报，将重新生成")
            use_existing = False

        # 3. 根据选择生成或加载报告
        if use_existing:
            print("\n[INFO] 使用现有报告")
            personal_report_map = existing_personal_reports
            project_report_paths = [(name, path) for name, path in existing_project_reports.items()]
        else:
            # 询问用户是否有特殊要求
            print("\n请输入对周报的特殊要求（直接回车跳过）：")
            user_requirement = input("> ").strip()
            if not user_requirement:
                user_requirement = None

            # 生成个人周报
            print("\n=== 生成个人周报 ===")
            personal_report_map = {}
            for member in selected_members:
                # 先检查该成员是否有实际代码变更
                has_diff = False
                for project in member.get("project_roles", {}).keys():
                    repo_path = get_repo_path_for_project(project)
                    if not repo_path:
                        continue
                    git_author = member.get("git_name") or member.get("name") or member.get("email")
                    diff = get_git_diff(repo_path, author=git_author)
                    if diff and "本周无代码变更" not in diff and "（git diff执行失败）" not in diff and "（执行异常）" not in diff:
                        has_diff = True
                        break
                    diff_email = get_git_diff(repo_path, author=member.get("email"))
                    if diff_email and "本周无代码变更" not in diff_email and "（git diff执行失败）" not in diff_email and "（执行异常）" not in diff_email:
                        has_diff = True
                        break
                if not has_diff:
                    print(f"[WARN] {member['name']} <{member['email']}> 本周无代码变更，跳过生成周报")
                    continue

                ctx, roles_str = generate_personal_context(member, team_members)
                role_display = get_roles_display(roles_str)
                print(f"--- 为 {member['name']}（{role_display}）生成周报 ---")
                report = generate_report(
                    ctx,
                    PERSONAL_WEEKLY_PROMPT_FILE,
                    user_requirement,
                    MY_NAME=member['name'],
                    MY_ROLE=role_display,
            MY_GIT_NAME=member.get('git_name') or member.get('name') or '',
                    MY_EMAIL=member['email']
                )
                filepath = os.path.join(person_output_dir, f"{member['name']}_{member['email']}_周报_{date_str}.md")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(report)
                personal_report_map[member['email']] = (member, filepath)
                print(f"[OK] {member['name']} 周报已保存: {filepath}")

            # 生成项目周报
            print("\n=== 生成项目周报 ===")
            project_report_paths = []
            for project in PROJECTS:
                print(f"--- 为 {get_project_name(project)} 生成周报 ---")
                ctx = generate_project_context(project, team_members)
                report = generate_report(
                    ctx,
                    PROJECT_WEEKLY_PROMPT_FILE,
                    user_requirement,
                    PROJECT_NAME=get_project_name(project),
                    PROJECT_DIR=project
                )
                filepath = os.path.join(project_output_dir, f"{get_project_name(project)}_周报_{date_str}.md")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(report)
                project_report_paths.append((project, filepath))
                print(f"[OK] {get_project_name(project)} 周报已保存: {filepath}")

        print(f"\n[INFO] 输出目录: {output_base}")
        print(f"[INFO] 个人周报: {person_output_dir}")
        print(f"[INFO] 项目周报: {project_output_dir}")

        # 4. 确认发送邮件
        if EMAIL_ENABLED:
            print("\n" + "=" * 60)
            print("邮件发送确认")
            print("=" * 60)
            print("\n【周报文件】")
            personal_emails = [member['email'] for (member, path) in personal_report_map.values()]
            project_emails = []
            for proj_name, path in project_report_paths:
                recips = PROJECT_REPORT_RECIPIENTS.get(proj_name, DEFAULT_PROJECT_RECIPIENTS)
                project_emails.extend(recips if recips else [])
            for name, (member, path) in personal_report_map.items():
                print(f"  个人周报 - {name} <{member['email']}>: {path}")
            for proj_name, path in project_report_paths:
                print(f"  项目周报 - {proj_name}: {path}")
            print(f"\n个人周报发至: {', '.join(personal_emails)}")
            print(f"项目周报发至: {', '.join(project_emails)}")
            print("\n请先预览以上报告文件，确认无误后再选择发送邮件。")
            print("\n选择发送方式:")
            print("1. 发送全部邮件（个人周报 + 项目周报）")
            print("2. 仅发送个人周报邮件")
            print("3. 仅发送项目周报邮件")
            print("4. 仅发送个人周报给指定成员")
            print("5. 不发送邮件")
            choice = input("\n请输入选项 (1-5，直接回车默认发送全部): ").strip()

            if choice == "" or choice == "1":
                # 发送全部邮件
                for name, (member, path) in personal_report_map.items():
                    send_personal_report_email(member, path, "周报")
                for proj_name, path in project_report_paths:
                    recipients = PROJECT_REPORT_RECIPIENTS.get(proj_name, DEFAULT_PROJECT_RECIPIENTS)
                    if recipients:
                        send_project_report_email(proj_name, path, "周报", recipients)
            elif choice == "2":
                # 仅发送个人周报
                for name, (member, path) in personal_report_map.items():
                    send_personal_report_email(member, path, "周报")
            elif choice == "3":
                # 仅发送项目周报
                for proj_name, path in project_report_paths:
                    recipients = PROJECT_REPORT_RECIPIENTS.get(proj_name, DEFAULT_PROJECT_RECIPIENTS)
                    if recipients:
                        send_project_report_email(proj_name, path, "周报", recipients)
            elif choice == "4":
                # 仅发送个人周报给指定成员
                # 收集git提交中所有作者邮箱（去重）
                all_author_emails = {}
                repo_map = {k: v["local"] for k, v in PROJECTS.items()}
                for project, repo_path in repo_map.items():
                    for author in get_git_authors(repo_path):
                        all_author_emails[author["email"]] = author
                # 添加PERSONAL_REPORT_RECIPIENT中的邮箱
                for email in PERSONAL_REPORT_RECIPIENT:
                    if email not in all_author_emails:
                        all_author_emails[email] = {"name": email.split("@")[0], "email": email, "git_name": ""}
                # 构建候选列表（成员优先，再是额外的邮件地址）
                candidates = list(personal_report_map.keys())
                extra_emails = [email for email in all_author_emails if email not in candidates]
                all_candidates = candidates + extra_emails

                print("\n选择发送个人周报的成员:")
                print("0. 不发送")
                for i, email in enumerate(all_candidates, 1):
                    if email in candidates:
                        print(f"{i}. {email} [已生成周报]")
                    else:
                        author = all_author_emails[email]
                        print(f"{i}. {author['name']} <{email}> [仅抄送]")
                member_choice = input("\n请输入编号（用逗号分隔，如 1,3）: ").strip()
                if member_choice == "0":
                    print("[INFO] 取消发送")
                else:
                    try:
                        indices = [int(x.strip()) - 1 for x in member_choice.split(",")]
                        for i in indices:
                            if 0 <= i < len(candidates):
                                name = candidates[i]
                                member, path = personal_report_map[name]
                                send_personal_report_email(member, path, "周报")
                            elif i < len(all_candidates):
                                email = all_candidates[i]
                                if email in extra_emails:
                                    print(f"[INFO] 邮件地址 {email} 无对应周报文件，跳过")
                    except ValueError:
                        print("[ERROR] 输入无效，取消发送")
            else:
                print("[INFO] 取消发送邮件")
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        sys.exit(1)