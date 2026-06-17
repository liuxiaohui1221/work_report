#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用工作汇报脚本（日报/周报）。

特点：
- 不影响 weekly_report.py / daily_report.py 已配置的定时任务
- 支持 --format NAME 动态指定汇报格式（不传 = default = 现有默认 prompt）
- 完全非交互式（所有选择走命令行参数）
- 自动从 git 提交发现成员，支持按邮箱 / 名称 / 别名匹配并合并多账号
- 可选 --send 自动发邮件

用法：
    # 周报，默认格式（等价于现有 weekly_report.py 的行为）
    python report.py --user liuxiaohui

    # 自定义汇报格式
    python report.py --user liuxiaohui --format cyber

    # 日报
    python report.py --type daily --user liuxiaohui

    # 生成完直接发邮件
    python report.py --user liuxiaohui --send

    # 自定义收件人（覆盖 config 里的默认）
    python report.py --user liuxiaohui --recipients "a@x.com,b@x.com"

    # 列出所有可用汇报格式
    python report.py --list-formats

汇报格式查找规则（以 --type weekly --format NAME 为例）：
    1) prompts/personal_weekly_prompt_<NAME>.md（推荐命名）
    2) prompts/<NAME>/personal_weekly_prompt.md
    3) prompts/personal_weekly_<NAME>.md
    4) prompts/personal_weekly_prompt.md（fallback，等价 --format default）
    项目报告 prompt 同理，文件名 personal 换成 project。

如果不传 --format 或传 default，则行为与现有 weekly_report.py / daily_report.py 完全一致。
"""

import argparse
import contextlib
import io
import os
import sys
from datetime import datetime

# 加入当前目录到 import 路径，便于复用 weekly_report / daily_report / email_sender
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# === 安全 import：daily_report.py:40 有一行 print(MINIMAX_API_KEY)，会无条件把
# API key 输出到 stdout，任何 import 这个模块的脚本都会触发泄露。
# 这里在 import 时把 stdout 重定向到黑洞，避免 key 被打到屏幕 / 日志 / commit message 里。
# 强烈建议尽快删掉 daily_report.py:40 的 print(MINIMAX_API_KEY) 这一行。
with contextlib.redirect_stdout(io.StringIO()):
    import weekly_report
    import daily_report
    import email_sender
from config import (  # noqa: E402  必须在 safe import 之后
    PROJECTS,
    EMAIL_ENABLED,
    PERSONAL_REPORT_RECIPIENT,
    PROJECT_REPORT_RECIPIENTS,
    DEFAULT_PROJECT_RECIPIENTS,
    EMAIL_SMTP_USER,
    MAX_DIFF_LINES,
    MAX_TOKENS,
    TEMPERATURE,
)
from email_sender import (  # noqa: E402  必须在 safe import 之后
    send_personal_report_email,
    send_project_report_email,
    reset_email_rate_limit,
)

# === Monkey-patch generate_report 用 streaming 模式 ===
# 原因：M3 模型（及部分新模型）Anthropic SDK 必须 streaming。原 weekly_report.py
# 用的 messages.create() 同步调用在 M3 上会抛 "Streaming is required for
# operations that may take longer than 10 minutes" 错误。
# 在 report.py 里运行时替换，不动 weekly_report.py / daily_report.py 源码。
import anthropic  # noqa: E402

# LLM 配置从 .env 拿（和 weekly_report.py 一致）
_MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")
_MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/anthropic")
_MODEL_NAME = os.getenv("MODEL_NAME", "MiniMax-M2.7")


def _generate_report_streaming(context, prompt_file, user_requirement=None, **format_kwargs):
    """用 streaming 模式调 LLM 跑 report 生成（兼容 M2.7 / M3）。"""
    client = anthropic.Anthropic(base_url=_MINIMAX_BASE_URL, api_key=_MINIMAX_API_KEY)
    prompt_template = weekly_report.load_prompt_file(prompt_file)
    system_prompt = prompt_template.format(**format_kwargs)
    user_message = context
    if user_requirement:
        user_message = f"## 用户特殊要求\n{user_requirement}\n\n---\n\n{context}"
    with client.messages.stream(
        model=_MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": [{"type": "text", "text": user_message}]}],
        temperature=TEMPERATURE,
    ) as stream:
        return stream.get_final_text()


weekly_report.generate_report = _generate_report_streaming
daily_report.generate_report = _generate_report_streaming

DEFAULT_FORMAT = "default"
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts")


# ---------------------------------------------------------------------------
# 汇报格式查找
# ---------------------------------------------------------------------------

def resolve_prompt_path(report_type: str, role: str, format_name: str) -> tuple:
    """根据汇报类型和格式名解析 prompt 文件路径。

    Args:
        report_type: 'weekly' 或 'daily'
        role: 'personal' 或 'project'
        format_name: 汇报格式名（如 default / cyber / executive）

    Returns:
        (resolved_path, used_format_name)
        - resolved_path: 实际使用的 prompt 文件绝对路径
        - used_format_name: 实际使用的格式名（如果 fallback 到 default，名字会变成 default）
    """
    # default 走 hardcoded 默认路径（与 weekly_report.py / daily_report.py 等价）
    if format_name == DEFAULT_FORMAT or not format_name:
        if report_type == "weekly":
            return (
                os.path.join(PROMPTS_DIR, f"{role}_weekly_prompt.md"),
                DEFAULT_FORMAT,
            )
        else:
            return (
                os.path.join(PROMPTS_DIR, f"{role}_daily_prompt.md"),
                DEFAULT_FORMAT,
            )

    # 自定义格式的查找顺序
    candidates = [
        os.path.join(PROMPTS_DIR, f"{role}_{report_type}_prompt_{format_name}.md"),
        os.path.join(PROMPTS_DIR, format_name, f"{role}_{report_type}_prompt.md"),
        os.path.join(PROMPTS_DIR, f"{role}_{report_type}_{format_name}.md"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path, format_name

    # fallback 到 default，并打印警告
    fallback_path, _ = resolve_prompt_path(report_type, role, DEFAULT_FORMAT)
    print(
        f"[WARN] 未找到汇报格式 '{format_name}' 对应的 prompt 文件，"
        f"已 fallback 到默认格式。查找路径：\n  "
        + "\n  ".join(candidates)
    )
    return fallback_path, DEFAULT_FORMAT


def list_available_formats(report_type: str = "weekly") -> list:
    """列出所有可用的汇报格式（扫描 prompts 目录）。"""
    if not os.path.isdir(PROMPTS_DIR):
        return [DEFAULT_FORMAT]
    formats = {DEFAULT_FORMAT}
    for fname in os.listdir(PROMPTS_DIR):
        if not fname.endswith(".md"):
            continue
        # 匹配 personal_weekly_prompt_<NAME>.md
        prefix = f"personal_{report_type}_prompt_"
        if fname.startswith(prefix) and fname.endswith(".md"):
            formats.add(fname[len(prefix):-3])
        # 匹配 personal_weekly_<NAME>.md
        prefix2 = f"personal_{report_type}_"
        if fname.startswith(prefix2) and "_prompt_" not in fname and fname.endswith(".md"):
            name = fname[len(prefix2):-3]
            # 过滤掉默认文件 personal_weekly_prompt.md 自身
            if name != "prompt":
                formats.add(name)
    return sorted(formats)


# ---------------------------------------------------------------------------
# 成员匹配
# ---------------------------------------------------------------------------

def discover_members(report_type: str) -> list:
    """从 git 自动发现候选成员（按汇报类型选时间范围）。"""
    if report_type == "weekly":
        # 复用 weekly_report 的发现逻辑（带周报日期范围）
        return weekly_report.discover_team_members_from_git()
    else:
        return daily_report.discover_team_members_from_git()


def match_member(user_query: str, candidates: list) -> list:
    """根据用户输入匹配候选成员，并合并所有匹配的 email 账号为同一个人。

    匹配规则（双向包含 + 同 name 合并）：
        1) 完全匹配 name / email / git_name
        2) query 是字段的子串（如 'xiaohui' 匹配 'xiaohui@qq.com'）
        3) 字段是 query 的子串（如 '刘小辉' 匹配 'xiaohui' 因为 'xiaohui' 是 '刘小辉' 的拼音一部分）
        4) 命中任一字段后，自动合并所有 name 相同的候选账号

    Args:
        user_query: 用户输入（邮箱 / 名称 / 别名，不区分大小写）
        candidates: discover_members() 返回的候选成员列表

    Returns:
        合并后的成员 dict（含 all_emails 字段）列表。如果没匹配到返回空 list。
    """
    query_lower = user_query.lower()

    matched_emails = set()
    matched_names = set()
    for c in candidates:
        name = (c.get("name") or "").lower()
        email = (c.get("email") or "").lower()
        git_name = (c.get("git_name") or "").lower()
        # 双向包含 + 完全匹配
        hit = (
            query_lower == name
            or query_lower == email
            or query_lower == git_name
            or (name and (query_lower in name or name in query_lower))
            or (email and (query_lower in email or email in query_lower))
            or (git_name and (query_lower in git_name or git_name in query_lower))
        )
        if hit:
            matched_emails.add(c["email"])
            matched_names.add(c["name"])

    if not matched_emails:
        return []

    # 同名合并：把所有 name 相同的账号也拉进来（如 刘小辉 有 xiaohui@ 和 liuxiaohui@ 两个 email）
    for c in candidates:
        if c["name"] in matched_names:
            matched_emails.add(c["email"])

    # 选 primary（优先级：git_name 命中 > 第一个；保持发件人是用户实际能收的邮箱）
    primary = None
    # 1) 优先 git_name 命中（让 primary.email 是用户实际能收的邮箱）
    for c in candidates:
        if c["email"] in matched_emails and (c.get("git_name") or "").lower() in query_lower:
            primary = c
            break
    # 2) 兜底用第一个
    if primary is None:
        for c in candidates:
            if c["email"] in matched_emails:
                primary = c
                break

    # display_name 单独解析：用于文件名 / 报告里的 MY_NAME
    # 优先 @datacyber.com 邮箱对应的 git author name（更"正式"的中文名）
    display_name = primary["name"]
    for c in candidates:
        if c["email"] in matched_emails and c["email"].lower().endswith("@datacyber.com"):
            display_name = c["name"]
            break

    return [{
        "name": primary["name"],
        "email": primary["email"],
        "git_name": primary.get("git_name", primary["name"]),
        "all_emails": sorted(matched_emails),
        "project_roles": primary.get("project_roles", {}),
        "display_name": display_name,
    }]


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def generate_personal_report(member: dict, report_type: str, format_name: str) -> str:
    """为单个成员生成个人报告。返回生成的报告内容。"""
    prompt_path, used_format = resolve_prompt_path(report_type, "personal", format_name)
    if report_type == "weekly":
        ctx, roles_str = weekly_report.generate_personal_context(member, [member])
    else:
        ctx, roles_str = daily_report.generate_personal_context(member, [member])

    role_display = _get_roles_display(roles_str)
    if report_type == "weekly":
        return weekly_report.generate_report(
            ctx,
            prompt_path,
            user_requirement=None,
            MY_NAME=member.get("display_name") or member["name"],
            MY_ROLE=role_display,
            MY_GIT_NAME=member.get("git_name") or member.get("name") or "",
            MY_EMAIL=member["email"],
        )
    else:
        return daily_report.generate_report(
            ctx,
            prompt_path,
            MY_NAME=member.get("display_name") or member["name"],
            MY_ROLE=role_display,
            MY_GIT_NAME=member.get("git_name") or member.get("name") or "",
            MY_EMAIL=member["email"],
        )


def generate_project_report(project: str, all_members: list, report_type: str, format_name: str) -> str:
    """为单个项目生成项目报告。返回生成的报告内容。"""
    prompt_path, used_format = resolve_prompt_path(report_type, "project", format_name)
    project_name = _get_project_name(project)
    if report_type == "weekly":
        ctx = weekly_report.generate_project_context(project, all_members)
    else:
        ctx = daily_report.generate_project_context(project, all_members)

    if report_type == "weekly":
        return weekly_report.generate_report(
            ctx,
            prompt_path,
            user_requirement=None,
            PROJECT_NAME=project_name,
            PROJECT_DIR=project,
        )
    else:
        return daily_report.generate_report(
            ctx,
            prompt_path,
            PROJECT_NAME=project_name,
            PROJECT_DIR=project,
        )


def _get_project_name(project_key: str) -> str:
    if project_key in PROJECTS:
        return PROJECTS[project_key]["name"]
    return project_key


def _get_role_display(role: str) -> str:
    role_map = {
        "team_leader": "团队负责人",
        "developer": "开发人员",
        "architecture": "架构师",
    }
    return role_map.get(role, role)


def _get_roles_display(roles_str: str) -> str:
    roles = [r.strip() for r in roles_str.split(",") if r.strip()]
    return "、".join(_get_role_display(r) for r in roles)


# ---------------------------------------------------------------------------
# 输出文件
# ---------------------------------------------------------------------------

def make_output_paths(report_type: str) -> tuple:
    """返回 (output_base, person_dir, project_dir)。"""
    today = datetime.now()
    year_month = today.strftime("%Y%m")
    if report_type == "weekly":
        # 周报目录结构：output/YYYYMM/<week_start_yyyymmdd>/by_person|by_project
        # 复用 weekly_report.py 的 week_folder 逻辑
        from datetime import timedelta
        monday = today - timedelta(days=today.weekday())
        if today.weekday() == 0:
            week_start = monday - timedelta(days=7)
        else:
            week_start = monday
        week_folder = week_start.strftime("%Y%m%d")
        output_base = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "output", year_month, week_folder
        )
        person_dir = os.path.join(output_base, "by_person")
        project_dir = os.path.join(output_base, "by_project")
    else:
        # 日报目录结构：output/YYYYMM/DD/by_person/daily|by_project/daily
        day = today.strftime("%d")
        output_base = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "output", year_month, day
        )
        person_dir = os.path.join(output_base, "by_person", "daily")
        project_dir = os.path.join(output_base, "by_project", "daily")
    os.makedirs(person_dir, exist_ok=True)
    os.makedirs(project_dir, exist_ok=True)
    return output_base, person_dir, project_dir


def save_report(content: str, filepath: str) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)


def person_filename(member: dict, report_type: str, date_desc: str) -> str:
    today_str = datetime.now().strftime("%Y-%m-%d")
    # 优先用 display_name（如"刘小辉"），fallback 到 primary.name（如"xiaohui"）
    name = member.get("display_name") or member["name"]
    return f"{name}_{report_type == 'weekly' and '周报' or '日报'}_{today_str}_{date_desc}.md"


def project_filename(project: str, report_type: str, date_desc: str) -> str:
    today_str = datetime.now().strftime("%Y-%m-%d")
    return f"{_get_project_name(project)}_{report_type == 'weekly' and '周报' or '日报'}_{today_str}_{date_desc}.md"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="通用工作汇报脚本（日报/周报），支持动态汇报格式。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--type", choices=["daily", "weekly"], default="weekly",
        help="报告类型：daily=日报，weekly=周报（默认 weekly）",
    )
    parser.add_argument(
        "--format", dest="format_name", default=DEFAULT_FORMAT,
        help=f"汇报格式名（默认 {DEFAULT_FORMAT}，等价现有默认 prompt）。"
             f"格式名对应的 prompt 文件查找规则见脚本注释。",
    )
    parser.add_argument(
        "--user", action="append", default=[],
        help="指定要生成报告的成员（可多次传匹配多人）。"
             "支持邮箱 / 名称 / git 用户名 / 别名匹配，多账号自动合并。"
             "不传则从 git 自动发现的所有成员都生成。",
    )
    parser.add_argument(
        "--send", action="store_true",
        help="生成完报告后直接发邮件（默认只生成不发）",
    )
    parser.add_argument(
        "--recipients", default=None,
        help="自定义收件人列表（逗号分隔），覆盖 config 里的 PROJECT_REPORT_RECIPIENTS。"
             "个人报告收件人始终是成员本人（cc = PERSONAL_REPORT_RECIPIENT）。",
    )
    parser.add_argument(
        "--list-formats", action="store_true",
        help="列出所有可用的汇报格式后退出",
    )
    parser.add_argument(
        "--include-projects", action="store_true",
        help="同时生成项目报告（默认只生成个人报告）",
    )
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    # 列出可用格式
    if args.list_formats:
        formats = list_available_formats(args.type)
        print(f"可用汇报格式（--type {args.type}）：")
        for f in formats:
            print(f"  - {f}")
        print(f"\n当前选择: {args.format_name}")
        return 0

    # 解析 prompt 路径（提前检查格式是否存在）
    personal_prompt_path, used_format = resolve_prompt_path(args.type, "personal", args.format_name)
    if used_format != args.format_name:
        print(f"[WARN] 汇报格式 '{args.format_name}' 不可用，已 fallback 到 '{used_format}'")
    print(f"[INFO] 报告类型: {args.type}, 汇报格式: {used_format}")
    print(f"[INFO] 个人 prompt: {personal_prompt_path}")
    if args.include_projects:
        project_prompt_path, _ = resolve_prompt_path(args.type, "project", args.format_name)
        print(f"[INFO] 项目 prompt: {project_prompt_path}")

    # 发现成员
    candidates = discover_members(args.type)
    if not candidates:
        print("[ERROR] 没有从 git 发现任何成员（统计范围内无 commit）")
        return 1

    # 按 --user 过滤成员
    if args.user:
        selected_members = []
        for q in args.user:
            matched = match_member(q, candidates)
            if not matched:
                print(f"[WARN] 未匹配到成员: {q}（git 候选：{[c['email'] for c in candidates]}）")
            else:
                selected_members.extend(matched)
        # 去重（按 email）
        seen = set()
        unique = []
        for m in selected_members:
            key = m["email"]
            if key not in seen:
                seen.add(key)
                unique.append(m)
        selected_members = unique
    else:
        selected_members = candidates

    if not selected_members:
        print("[ERROR] 没有选中任何成员")
        return 1

    print(f"[INFO] 将为以下 {len(selected_members)} 位成员生成报告：")
    for m in selected_members:
        emails_str = ", ".join(m.get("all_emails", [m["email"]]))
        print(f"  - {m['name']} <{m['email']}> (账号: {emails_str})")

    # 输出目录
    output_base, person_dir, project_dir = make_output_paths(args.type)
    print(f"[INFO] 输出目录: {output_base}")

    # 生成个人报告
    today_str = datetime.now().strftime("%Y-%m-%d")
    date_desc = today_str  # 简化日期描述
    personal_report_paths = []
    for member in selected_members:
        try:
            print(f"--- 生成 {member['name']} 的个人{'周' if args.type == 'weekly' else '日'}报 ---")
            report_content = generate_personal_report(member, args.type, used_format)
            filename = person_filename(member, args.type, date_desc)
            filepath = os.path.join(person_dir, filename)
            save_report(report_content, filepath)
            print(f"[OK] 已保存: {filepath}")
            personal_report_paths.append((member, filepath))
        except Exception as e:
            print(f"[ERROR] 生成 {member['name']} 报告失败: {type(e).__name__}: {e}")
            return 1

    # 生成项目报告
    project_report_paths = []
    if args.include_projects:
        print("\n=== 生成项目报告 ===")
        for project_key in PROJECTS:
            try:
                print(f"--- 生成 {_get_project_name(project_key)} 的项目报告 ---")
                report_content = generate_project_report(
                    project_key, selected_members, args.type, used_format
                )
                filename = project_filename(project_key, args.type, date_desc)
                filepath = os.path.join(project_dir, filename)
                save_report(report_content, filepath)
                print(f"[OK] 已保存: {filepath}")
                project_report_paths.append((project_key, filepath))
            except Exception as e:
                print(f"[ERROR] 生成项目 {project_key} 报告失败: {type(e).__name__}: {e}")

    # 发邮件
    if args.send:
        if not EMAIL_ENABLED:
            print("[WARN] EMAIL_ENABLED=False，跳过发送")
        else:
            reset_email_rate_limit()
            print("\n=== 发送邮件 ===")
            for member, filepath in personal_report_paths:
                ok = send_personal_report_email(
                    member, filepath, "周报" if args.type == "weekly" else "日报"
                )
                print(f"  个人报告 -> {member['email']}: {'成功' if ok else '失败'}")
            for project_key, filepath in project_report_paths:
                if args.recipients:
                    recipients = [e.strip() for e in args.recipients.split(",") if e.strip()]
                else:
                    recipients = PROJECT_REPORT_RECIPIENTS.get(project_key, DEFAULT_PROJECT_RECIPIENTS)
                if recipients:
                    project_name = _get_project_name(project_key)
                    ok = send_project_report_email(
                        project_name, filepath,
                        "周报" if args.type == "weekly" else "日报",
                        recipients,
                    )
                    print(f"  项目报告 -> {recipients}: {'成功' if ok else '失败'}")
    else:
        print("\n[INFO] 报告已生成，未发送邮件。传 --send 自动发送。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
