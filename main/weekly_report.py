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
    PROJECT_REPORT_RECIPIENTS, DEFAULT_PROJECT_RECIPIENTS,
    PERSONAL_REPORT_RECIPIENT,
    GITLAB_URL, GITLAB_PRIVATE_TOKEN, GITLAB_API_MODE,
    FILTER_PROJECTS_WITHOUT_CHANGES, FILTER_AUTHOR_EMAIL,
    SEND_PROJECT_REPORT,
)
from email_sender import send_personal_report_email, send_project_report_email, compute_personal_recipients
from gitlab_client import GitLabClient, get_user_gitlab_projects, get_user_commits_from_gitlab
from sent_log import SentLog

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


def get_gitlab_commit_url(project_key: str, commit_hash: str) -> str:
    """根据项目键获取 GitLab commit 链接"""
    if project_key and project_key in PROJECTS:
        remote = PROJECTS[project_key].get("remote", "")
        if remote:
            # 将 .git 后缀去掉，获取项目基础 URL
            base_url = remote.rstrip("/").replace(".git", "")
            # GitLab commit URL 格式: {base_url}/-/commit/{hash}
            return f"{base_url}/-/commit/{commit_hash}"
    return commit_hash


def get_git_commits_with_hash(repo_path: str, project_key: str = None) -> str:
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
                    commit_url = get_gitlab_commit_url(project_key, commit_hash)
                    if commit_url != commit_hash:
                        # 可点击链接
                        formatted.append(f"- [{commit_hash}]({commit_url}) {message} ({author}, {date})")
                    else:
                        formatted.append(f"- [{commit_hash}] {message} ({author}, {date})")
                else:
                    formatted.append(line)
            return "\n".join(formatted)
        return f"获取Git日志失败: {result.stderr}"
    except FileNotFoundError:
        return "错误: 请确认已安装Git并加入PATH"
    except Exception as e:
        return f"执行Git命令异常: {e}"


def get_git_commits_with_hash_for_author(repo_path: str, author_name: str, author_email: str, project_key: str = None) -> str:
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
                    commit_url = get_gitlab_commit_url(project_key, commit_hash)
                    if commit_url != commit_hash:
                        # 可点击链接
                        formatted.append(f"- [{commit_hash}]({commit_url}) {message} ({author}, {date})")
                    else:
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
                    commit_url = get_gitlab_commit_url(project_key, commit_hash)
                    if commit_url != commit_hash:
                        # 可点击链接
                        formatted.append(f"- [{commit_hash}]({commit_url}) {message} ({author}, {date})")
                    else:
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


def read_local_plan_files(project: str = None, max_age_days: int = 0) -> str:
    """从本地读取 Excel 或 Markdown 规划文件，合并为文本

    2026-08-08 改造：检查文件 mtime，超过 max_age_days 天的文件视为过期，跳过不读。
    这样周报发送时只会用"最近更新过"的计划，避免 stale 数据。

    Args:
        project: 项目子目录名（如 "dataagent"）
        max_age_days: 最大允许的"未更新天数"，默认 0 = 只读今天改过的文件。
                       设为 7 = 最近一周改过的都接受。

    Returns:
        str: 合并后的计划文本。如果所有文件都过期或不存在，
             返回带"未找到可用计划文件"提示的占位文本。
    """
    from datetime import datetime, timedelta
    base_dir = PLAN_DATA_DIR
    if project:
        project_subdir = os.path.join(PLAN_DATA_DIR, project)
        # 如果项目子目录存在，优先从子目录读取；否则从根目录读取
        if os.path.isdir(project_subdir):
            base_dir = project_subdir
        else:
            base_dir = PLAN_DATA_DIR

    if not base_dir or not os.path.isdir(base_dir):
        return f"（未配置规划文件路径，请设置 PLAN_DATA_DIR）"

    today = datetime.now().date()
    cutoff = today - timedelta(days=max_age_days)
    skipped = []
    content_parts = []

    for f in os.listdir(base_dir):
        if not (f.endswith('.xlsx') or f.endswith('.md')):
            continue
        filepath = os.path.join(base_dir, f)
        mtime = datetime.fromtimestamp(os.path.getmtime(filepath)).date()
        if mtime < cutoff:
            skipped.append(f"{f} (mtime={mtime})")
            continue
        filename = os.path.basename(filepath)
        if filepath.endswith('.xlsx'):
            try:
                wb = openpyxl.load_workbook(filepath, data_only=True)
                sheet = wb.active
                lines = []
                for row in sheet.iter_rows(values_only=True):
                    row_str = "\t".join([str(c) if c is not None else "" for c in row])
                    lines.append(row_str)
                content_parts.append(f"### 文件: {filename} (Excel, mtime={mtime})\n" + "\n".join(lines))
            except Exception as e:
                content_parts.append(f"### 文件: {filename} (Excel) 读取失败: {e}")
        elif filepath.endswith('.md'):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    md_content = f.read()
                content_parts.append(f"### 文件: {filename} (Markdown, mtime={mtime})\n{md_content}")
            except Exception as e:
                content_parts.append(f"### 文件: {filename} (Markdown) 读取失败: {e}")

    if not content_parts:
        skip_msg = f"（跳过过期文件: {', '.join(skipped)}）" if skipped else ""
        return f"（未在 {project or '根目录'} 下找到 max_age_days={max_age_days} 内的计划文件，请更新后重跑 {skip_msg}）"

    if skipped:
        print(f"[INFO] 跳过过期计划文件: {', '.join(skipped)}")
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


def member_has_changes_in_project(member: dict, project: str) -> bool:
    """检查成员在指定项目中是否有代码变更"""
    if not FILTER_PROJECTS_WITHOUT_CHANGES:
        return True

    repo_path = get_repo_path_for_project(project)
    if not repo_path or not os.path.exists(repo_path):
        return False

    all_emails = member.get("all_emails", [member.get("email", "")])
    for email in all_emails:
        diff = get_git_diff(repo_path, author=email)
        if diff and "本周无代码变更" not in diff and "（git diff执行失败）" not in diff and "（执行异常）" not in diff:
            return True
    return False


def get_project_name(project: str) -> str:
    """获取项目显示名称"""
    if project in PROJECTS:
        return PROJECTS[project]["name"]
    return project


def generate_personal_context(member: dict, all_members: list,
                              use_gitlab: bool = False,
                              gitlab_url: str = None,
                              gitlab_token: str = None) -> tuple:
    """生成个人周报上下文

    Args:
        member: 成员信息 dict
        all_members: 所有成员列表
        use_gitlab: 是否从 GitLab 获取数据（不依赖本地 PROJECTS）
        gitlab_url: GitLab 服务器地址
        gitlab_token: GitLab 私有 token
    """
    if use_gitlab and gitlab_url and gitlab_token:
        return generate_personal_context_from_gitlab(member, all_members, gitlab_url, gitlab_token)

    # 原有 PROJECTS 模式逻辑
    plan_files = {}
    git_commits = {}
    personal_diffs = {}
    personal_commits_with_hash = {}
    project_role_map = member["project_roles"]
    all_emails = member.get("all_emails", [member["email"]])

    # 过滤出成员有变更的项目
    active_projects = []
    for project in project_role_map.keys():
        if member_has_changes_in_project(member, project):
            active_projects.append(project)

    if not active_projects:
        context = f"""### 本周无代码变更

本周在所有项目中均无代码变更。

人员信息：{member.get('name', '')}，Git用户名：{member.get('git_name', '')}，邮箱：{member.get('email', '')}"""
        return context, ",".join(set(project_role_map.values()))

    for project in active_projects:
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
            commits = get_git_commits_with_hash_for_author(repo_path, email, email, project_key=project)
            if commits and "本周无提交记录" not in commits:
                merged_commit_lines.append(f"**[{email}]**\n{commits}")

        personal_diffs[project] = "\n\n".join(merged_diff_lines) if merged_diff_lines else f"**{project}**\n本周无代码变更"
        personal_commits_with_hash[project] = "\n\n".join(merged_commit_lines) if merged_commit_lines else f"**{project}**\n本周无提交记录"

    plan_parts = []
    for project in active_projects:
        plan_parts.append(f"**{get_project_name(project)}（{project}目录）**\n{plan_files[project]}")

    commit_parts = []
    diff_parts = []
    for project in active_projects:
        commit_parts.append(f"**{get_project_name(project)}**\n{git_commits[project]}")
        diff_parts.append(f"**{get_project_name(project)}**\n{personal_diffs[project]}")

    # 收集所有角色用于prompt
    all_roles = set()
    for project in active_projects:
        for r in project_role_map[project].split(","):
            all_roles.add(r.strip())

    # 本人提交记录（含hash）用于追溯
    personal_commit_parts = []
    for project in active_projects:
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


def generate_personal_context_from_gitlab(member: dict, all_members: list,
                                         gitlab_url: str, private_token: str) -> tuple:
    """从 GitLab 动态获取数据，生成个人周报上下文（不依赖 PROJECTS 配置）"""
    start, end = get_week_date_range()
    since = start.strftime("%Y-%m-%d")
    until = end.strftime("%Y-%m-%d")

    all_emails = member.get("all_emails", [member["email"]])
    primary_email = member["email"]

    # 从 GitLab 获取用户在所有项目中的提交
    project_commits = get_user_commits_from_gitlab(gitlab_url, private_token, primary_email, since, until)

    if not project_commits:
        context = f"""### GitLab 项目提交（本周 {since} ~ {until}）

未从 GitLab 获取到任何项目提交记录，可能是：
1. GitLab Token 权限不足
2. 该邮箱在 GitLab 上没有提交记录
3. GitLab 服务器不可达

人员信息：{member.get('name', '')}，Git用户名：{member.get('git_name', '')}，邮箱：{member.get('email', '')}"""
        return context, "developer"

    # 按项目组织上下文
    commit_parts = []
    diff_parts = []
    personal_commit_parts = []

    for project_path, project_data in project_commits.items():
        project_name = project_data.get("name", project_path)
        web_url = project_data.get("web_url", "")

        # 全部成员的提交（只显示该用户自己的）
        commit_parts.append(f"**{project_name}** ({project_path})\n{project_data.get('commits', '本周无提交记录')}")

        # 本人提交记录（含 hash）
        personal_commit_parts.append(f"**{project_name}** ({project_path})\n{project_data.get('commits', '本周无提交记录')}")

        # 本人 diff
        diff_text = project_data.get('diff', '本周无代码变更')
        diff_parts.append(f"**{project_name}** ({project_path})\n{diff_text}")

    context = f"""### GitLab 项目提交（本周 {since} ~ {until}）

以下是本人在 GitLab 上有权限的所有项目的提交记录（按项目分类）：

### 本周 Git 提交记录（全部成员）

{chr(10).join(commit_parts)}

### 本人本周提交记录（含提交号，用于追溯）

{chr(10).join(personal_commit_parts)}

### 本人本周代码变更 (Diff)

{chr(10).join(diff_parts)}

人员信息：{member.get('name', '')}，Git用户名：{member.get('git_name', '')}，邮箱：{member.get('email', '')}"""
    return context, "developer"


def generate_project_context(project: str, all_members: list) -> str:
    """生成项目周报上下文

    2026-08-08 改造：在"全部成员提交"基础上，增加"各成员提交（含追溯链接）"段。
    原因：format_commit_appendix 正则只识别 `- [hash](url) ... (author, YYYY-MM-DD)` 链接格式，
    get_git_commits 返回的 `- hash - message` 格式不被识别，会导致项目周报漏掉 commit 附录。
    修法：每个成员用 get_git_commits_with_hash_for_author 单独拉一次，拼出 hash-link 段。
    """
    repo_path = get_repo_path_for_project(project)
    all_commits = get_git_commits(repo_path)
    plan_text = read_local_plan_files(project)

    member_diffs = []
    member_commits_with_hash = []
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

            # 拉该成员本周提交（含 hash 链接），供 format_commit_appendix 抽取
            member_email = member.get("email", "")
            member_commits = get_git_commits_with_hash_for_author(
                repo_path, member.get("name", ""), member_email, project_key=project
            )
            if member_commits and "本周无提交记录" not in member_commits:
                member_commits_with_hash.append(f"**[{member['name']} <{member_email}>]**\n{member_commits}")

    commits_with_hash_section = "\n\n".join(member_commits_with_hash) if member_commits_with_hash else "本周无提交记录"

    context = f"""### 项目：{get_project_name(project)}

### 项目规划（{project}目录）
{plan_text}

### 本周 Git 提交记录（全部成员）
{all_commits}

### 各成员提交记录（含提交号，用于追溯）
{commits_with_hash_section}

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
        text = stream.get_final_text()

    # 兜底：去掉 LLM 误包的 ```markdown ... ``` 围栏
    import re
    text = re.sub(r'^```(?:markdown|md)?\s*\n', '', text.strip())
    text = re.sub(r'\n```\s*$', '', text)
    return text.strip()


def format_commit_appendix(commits_text: str, max_lines: int = 30) -> str:
    """把 commit 文本压缩成可追溯的附录（不计正文 600 字限制）
    只识别 commit 行（形如 `- [hash](url) message (author, YYYY-MM-DD)`），
    过滤掉 diff 内容（避免把代码变更误识别为 commit）。
    """
    if not commits_text or "本周无提交" in commits_text:
        return ""
    import re
    # 匹配 commit 行：- [hash](url) ... (author, YYYY-MM-DD)
    commit_pattern = re.compile(r'^\s*-\s+\[([0-9a-f]+)\]\([^)]+\)\s+.+\(\S+,\s*\d{4}-\d{2}-\d{2}\)')
    commit_lines = []
    for line in commits_text.splitlines():
        m = commit_pattern.match(line)
        if m:
            commit_lines.append(line.strip())
    if not commit_lines:
        return ""
    truncated = len(commit_lines) > max_lines
    commit_lines = commit_lines[:max_lines]
    appendix = "\n\n---\n\n## 📌 本周提交清单（追溯用）\n"
    for cl in commit_lines:
        cl_clean = cl.replace("**", "").strip()
        appendix += f"\n{cl_clean}"
    if truncated:
        appendix += f"\n\n> 共 {len(commit_lines)} 条，已截断，完整列表见 git log"
    return appendix


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

    # 测试模式：--test 强制只发给 liuxiaohui，CC 为空，主题加 [测试] 前缀
    # 防止迭代期间误发邮件给 zl/ypf/songhongxin 等真实收件人
    TEST_MODE = "--test" in sys.argv
    if TEST_MODE:
        sys.argv.remove("--test")
        print("=" * 60)
        print("⚠️  测试模式启用 ⚠️")
        print("  - 收件人强制为 liuxiaohui@datacyber.com")
        print("  - 抄送 (CC) 全部清空")
        print("  - 主题前缀 [测试]")
        print("  - sent_log 仍会记录（用 main/sent_log.py clear 清空）")
        print("=" * 60)

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

        # 判断是否使用 GitLab API 模式（不依赖 PROJECTS 配置）
        use_gitlab_api = GITLAB_API_MODE and GITLAB_PRIVATE_TOKEN
        if use_gitlab_api:
            print(f"\n[INFO] GitLab API 模式已启用，将从 {GITLAB_URL} 动态获取所有项目提交记录")
        else:
            if GITLAB_API_MODE and not GITLAB_PRIVATE_TOKEN:
                print("\n[WARNING] GITLAB_API_MODE=True 但 GITLAB_PRIVATE_TOKEN 未配置，将使用本地 PROJECTS 模式")

        # 1. 检查已存在的报告文件
        existing_personal_reports = {}
        existing_project_reports = {}

        for member in selected_members:
            filepath = os.path.join(person_output_dir, f"{member['name']}_{member['email']}_周报_{date_str}.md")
            if os.path.exists(filepath):
                existing_personal_reports[member['email']] = (member, filepath)

        # 2026-08-08 项目周报已关闭，不再加载已有的项目周报
        if not SEND_PROJECT_REPORT:
            existing_project_reports = {}
        else:
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
                # GitLab API 模式下跳过本地 PROJECTS 检查，直接从 GitLab 获取
                if not use_gitlab_api:
                    # 先检查该成员是否有实际代码变更（仅本地模式）
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

                ctx, roles_str = generate_personal_context(
                    member, team_members,
                    use_gitlab=use_gitlab_api,
                    gitlab_url=GITLAB_URL if use_gitlab_api else None,
                    gitlab_token=GITLAB_PRIVATE_TOKEN if use_gitlab_api else None
                )
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
                # 追加 commit 附录（不计正文字数）
                commit_appendix = format_commit_appendix(ctx, max_lines=20)
                if commit_appendix:
                    report = report.rstrip() + commit_appendix
                filepath = os.path.join(person_output_dir, f"{member['name']}_{member['email']}_周报_{date_str}.md")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(report)
                personal_report_map[member['email']] = (member, filepath)
                print(f"[OK] {member['name']} 周报已保存: {filepath}")

            # 生成项目周报（2026-08-08 关闭：SEND_PROJECT_REPORT=False 时跳过）
            if not SEND_PROJECT_REPORT:
                print("\n=== 项目周报已关闭（SEND_PROJECT_REPORT=False），跳过 ===")
                project_report_paths = []
            else:
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
                    # 追加 commit 附录（不计正文字数）
                    commit_appendix = format_commit_appendix(ctx, max_lines=30)
                    if commit_appendix:
                        report = report.rstrip() + commit_appendix
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
            if TEST_MODE:
                print("  ⚠️  测试模式：所有邮件只发给 liuxiaohui@datacyber.com，CC 为空")
            print("\n【周报文件】")
            personal_emails = [member['email'] for (member, path) in personal_report_map.values()]
            if TEST_MODE:
                personal_emails = ["liuxiaohui@datacyber.com"] * len(personal_emails)
            project_emails = []
            for proj_name, path in project_report_paths:
                recips = PROJECT_REPORT_RECIPIENTS.get(proj_name, DEFAULT_PROJECT_RECIPIENTS)
                if TEST_MODE:
                    recips = ["liuxiaohui@datacyber.com"]
                project_emails.extend(recips if recips else [])
            for name, (member, path) in personal_report_map.items():
                print(f"  个人周报 - {name} <{member['email']}>: {path}")
            for proj_name, path in project_report_paths:
                print(f"  项目周报 - {proj_name}: {path}")
            print(f"\n个人周报发至: {', '.join(personal_emails)}")
            print(f"项目周报发至: {', '.join(project_emails)}")
            print("\n请先预览以上报告文件，确认无误后再选择发送邮件。")
            print("\n选择发送方式:")
            if SEND_PROJECT_REPORT:
                print("1. 发送全部邮件（个人周报 + 项目周报）")
                print("2. 仅发送个人周报邮件")
                print("3. 仅发送项目周报邮件")
                print("4. 仅发送个人周报给指定成员")
                print("5. 不发送邮件")
            else:
                print("  ⚠️  项目周报已关闭（2026-08-08），只发送个人周报")
                print("1. 发送个人周报邮件")
                print("2. 不发送邮件")
            choice = input("\n请输入选项 (直接回车默认发送个人周报): ").strip()

            if not SEND_PROJECT_REPORT:
                # 项目周报已关闭：只发 / 不发 二选一
                send_done = False
                if choice in ("2", "5"):
                    print("[INFO] 取消发送")
                else:
                    if choice not in ("", "1"):
                        print("[INFO] 无效选项，默认发送个人周报")
                    # 走个人周报发送逻辑
                    sent_log = SentLog()
                    for name, (member, path) in personal_report_map.items():
                        if sent_log.is_sent(path):
                            print(f"[SKIP] {member['name']} 个人周报内容未变，已发送过，跳过")
                            continue
                        if TEST_MODE:
                            member_for_send = dict(member)
                            member_for_send['email'] = "liuxiaohui@datacyber.com"
                            to_emails = ["liuxiaohui@datacyber.com"]
                            cc_emails = []
                            if send_personal_report_email(member_for_send, path, "周报",
                                                          exclude_from_cc=list(PERSONAL_REPORT_RECIPIENT or []),
                                                          subject_prefix="[测试] "):
                                import re
                                date_match = re.search(r'_(\d{4}-\d{2}-\d{2})_', path)
                                ds = date_match.group(1) if date_match else date_str
                                sent_log.mark_sent(path, to_emails=to_emails, cc_emails=cc_emails,
                                                    subject=f"[测试] 【{member['name']}】{ds}",
                                                    report_type="personal")
                        else:
                            to_emails, cc_emails = compute_personal_recipients(member)
                            if send_personal_report_email(member, path, "周报"):
                                import re
                                date_match = re.search(r'_(\d{4}-\d{2}-\d{2})_', path)
                                ds = date_match.group(1) if date_match else date_str
                                sent_log.mark_sent(path, to_emails=to_emails, cc_emails=cc_emails,
                                                    subject=f"【{member['name']}】{ds}",
                                                    report_type="personal")
                send_done = True
                if send_done:
                    pass  # 跳过下面的 choice 分支
            elif choice == "" or choice == "1":
                # 发送全部邮件
                # 先算所有项目周报的主收件人，个人周报 CC 时排除这些人（Fix 1 去重）
                project_primary_recipients = set()
                project_send_plan = []
                for proj_name, path in project_report_paths:
                    recipients = PROJECT_REPORT_RECIPIENTS.get(proj_name, DEFAULT_PROJECT_RECIPIENTS)
                    if TEST_MODE:
                        recipients = ["liuxiaohui@datacyber.com"]
                    if recipients:
                        project_send_plan.append((proj_name, path, recipients))
                        project_primary_recipients.update(recipients)

                sent_log = SentLog()
                # 发送项目周报
                for proj_name, path, recipients in project_send_plan:
                    if sent_log.is_sent(path):
                        print(f"[SKIP] {proj_name} 项目周报内容未变，已发送过，跳过")
                        continue
                    subject_prefix = "[测试] " if TEST_MODE else ""
                    if send_project_report_email(proj_name, path, "周报", recipients,
                                                   subject_prefix=subject_prefix):
                        sent_log.mark_sent(path, to_emails=recipients,
                                            subject=f"{subject_prefix}【项目进度】{proj_name} {date_str}",
                                            report_type="project")

                # 发送个人周报（CC 排除已经是项目主收件人的人）
                for name, (member, path) in personal_report_map.items():
                    if sent_log.is_sent(path):
                        print(f"[SKIP] {member['name']} 个人周报内容未变，已发送过，跳过")
                        continue
                    if TEST_MODE:
                        # 测试模式：强制只发给 liuxiaohui，无 CC
                        member_for_send = dict(member)
                        member_for_send['email'] = "liuxiaohui@datacyber.com"
                        to_emails = ["liuxiaohui@datacyber.com"]
                        cc_emails = []
                        # 关键：把 PERSONAL_REPORT_RECIPIENT 整体作为 exclude_from_cc，
                        # 这样 cc_emails 计算后必为空
                        if send_personal_report_email(member_for_send, path, "周报",
                                                      exclude_from_cc=list(PERSONAL_REPORT_RECIPIENT or []),
                                                      subject_prefix="[测试] "):
                            import re
                            date_match = re.search(r'_(\d{4}-\d{2}-\d{2})_', path)
                            ds = date_match.group(1) if date_match else date_str
                            sent_log.mark_sent(path, to_emails=to_emails, cc_emails=cc_emails,
                                                subject=f"[测试] 【{member['name']}】{ds}",
                                                report_type="personal")
                    else:
                        to_emails, cc_emails = compute_personal_recipients(
                            member, exclude_from_cc=list(project_primary_recipients))
                        if send_personal_report_email(member, path, "周报",
                                                      exclude_from_cc=list(project_primary_recipients)):
                            import re
                            date_match = re.search(r'_(\d{4}-\d{2}-\d{2})_', path)
                            ds = date_match.group(1) if date_match else date_str
                            sent_log.mark_sent(path, to_emails=to_emails, cc_emails=cc_emails,
                                                subject=f"【{member['name']}】{ds}",
                                                report_type="personal")
            elif choice == "2":
                # 仅发送个人周报
                sent_log = SentLog()
                for name, (member, path) in personal_report_map.items():
                    if sent_log.is_sent(path):
                        print(f"[SKIP] {member['name']} 个人周报内容未变，已发送过，跳过")
                        continue
                    if TEST_MODE:
                        member_for_send = dict(member)
                        member_for_send['email'] = "liuxiaohui@datacyber.com"
                        to_emails = ["liuxiaohui@datacyber.com"]
                        cc_emails = []
                        if send_personal_report_email(member_for_send, path, "周报",
                                                      exclude_from_cc=list(PERSONAL_REPORT_RECIPIENT or []),
                                                      subject_prefix="[测试] "):
                            import re
                            date_match = re.search(r'_(\d{4}-\d{2}-\d{2})_', path)
                            ds = date_match.group(1) if date_match else date_str
                            sent_log.mark_sent(path, to_emails=to_emails, cc_emails=cc_emails,
                                                subject=f"[测试] 【{member['name']}】{ds}",
                                                report_type="personal")
                    else:
                        to_emails, cc_emails = compute_personal_recipients(member)
                        if send_personal_report_email(member, path, "周报"):
                            import re
                            date_match = re.search(r'_(\d{4}-\d{2}-\d{2})_', path)
                            ds = date_match.group(1) if date_match else date_str
                            sent_log.mark_sent(path, to_emails=to_emails, cc_emails=cc_emails,
                                                subject=f"【{member['name']}】{ds}",
                                                report_type="personal")
            elif SEND_PROJECT_REPORT and choice == "3":
                # 仅发送项目周报（2026-08-08 项目周报已关闭）
                if not SEND_PROJECT_REPORT:
                    print("[INFO] 项目周报已关闭（SEND_PROJECT_REPORT=False），跳过 choice 3")
                else:
                    sent_log = SentLog()
                    for proj_name, path in project_report_paths:
                        recipients = PROJECT_REPORT_RECIPIENTS.get(proj_name, DEFAULT_PROJECT_RECIPIENTS)
                        if TEST_MODE:
                            recipients = ["liuxiaohui@datacyber.com"]
                        if not recipients:
                            continue
                        if sent_log.is_sent(path):
                            print(f"[SKIP] {proj_name} 项目周报内容未变，已发送过，跳过")
                            continue
                        subject_prefix = "[测试] " if TEST_MODE else ""
                        if send_project_report_email(proj_name, path, "周报", recipients,
                                                       subject_prefix=subject_prefix):
                            sent_log.mark_sent(path, to_emails=recipients,
                                                subject=f"{subject_prefix}【项目进度】{proj_name} {date_str}",
                                                report_type="project")
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