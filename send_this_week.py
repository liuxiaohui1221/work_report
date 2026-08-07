#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发送本周周报（手动触发，已接入 sent_log 防重复）

自动定位本周的 by_person / by_person 目录下的所有周报文件，
跳过已发送的（基于 sent_log），发送剩余的。

用法：
    python send_this_week.py                # 发送本周所有未发的周报
    python send_this_week.py --force        # 忽略 sent_log 全部重发
    python send_this_week.py --dry-run      # 只看不发
"""

import os
import sys
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "main"))

from email_sender import send_personal_report_email, send_project_report_email, compute_personal_recipients
from sent_log import SentLog


def find_this_week_dir(output_dir: str) -> str:
    """找到本周的输出目录（output/YYYYMM/YYYYMMDD）"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() == 0:
        monday = monday - timedelta(days=7)
    week_folder = monday.strftime("%Y%m%d")
    year_month = today.strftime("%Y%m")
    return os.path.join(output_dir, year_month, week_folder)


def parse_personal_filename(filename: str):
    """从文件名解析出 {name, email}，例：刘小辉_liuxiaohui@datacyber.com_周报_2026-08-07.md"""
    base = filename[:-3] if filename.endswith(".md") else filename
    parts = base.split("_")
    if len(parts) < 3:
        return None
    name = parts[0]
    email = parts[1]
    return {"name": name, "email": email, "git_name": name, "all_emails": [email]}


def main():
    parser = argparse.ArgumentParser(description="发送本周周报（已接入 sent_log）")
    parser.add_argument("--force", action="store_true", help="忽略 sent_log，全部重发")
    parser.add_argument("--dry-run", action="store_true", help="只看不发")
    args = parser.parse_args()

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    week_dir = find_this_week_dir(output_dir)
    if not os.path.isdir(week_dir):
        print(f"[ERROR] 本周目录不存在: {week_dir}")
        print("       请先运行 weekly_report.py 生成周报")
        return 1

    sent_log = SentLog() if not args.force else None

    print("=" * 60)
    print(f"发送本周周报  ({week_dir})")
    print(f"  force={args.force}  dry_run={args.dry_run}")
    print("=" * 60)

    # 1. 项目周报
    project_dir = os.path.join(week_dir, "by_project")
    if os.path.isdir(project_dir):
        for fn in sorted(os.listdir(project_dir)):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(project_dir, fn)
            if sent_log and sent_log.is_sent(path):
                print(f"  [SKIP] {fn} (已发送过)")
                continue
            # 解析项目名（去 "周报_日期.md" 后缀）
            proj_name = fn.split("_周报_")[0]
            # 动态 import 避免循环依赖
            from config import PROJECT_REPORT_RECIPIENTS, DEFAULT_PROJECT_RECIPIENTS
            project_key = None
            for k, v in PROJECT_REPORT_RECIPIENTS.items():
                if v and proj_name in k or k in proj_name:
                    project_key = k
                    break
            if project_key is None:
                # 模糊匹配：用 PROJECTS 字典
                from config import PROJECTS
                for k, v in PROJECTS.items():
                    if v["name"] == proj_name or k in proj_name:
                        project_key = k
                        break
            recipients = PROJECT_REPORT_RECIPIENTS.get(project_key or proj_name, DEFAULT_PROJECT_RECIPIENTS)
            if not recipients:
                print(f"  [SKIP] {fn} (无项目收件人配置)")
                continue
            print(f"\n  [PROJECT] {proj_name} → {recipients}")
            if args.dry_run:
                continue
            if send_project_report_email(proj_name, path, "周报", recipients) and sent_log:
                sent_log.mark_sent(path, to_emails=recipients,
                                    subject=f"【项目进度】{proj_name}",
                                    report_type="project")

    # 2. 个人周报
    person_dir = os.path.join(week_dir, "by_person")
    if os.path.isdir(person_dir):
        for fn in sorted(os.listdir(person_dir)):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(person_dir, fn)
            if sent_log and sent_log.is_sent(path):
                print(f"  [SKIP] {fn} (已发送过)")
                continue
            member = parse_personal_filename(fn)
            if not member:
                print(f"  [SKIP] {fn} (文件名格式不对)")
                continue
            # CC 排除项目主收件人（Fix 1）
            from config import PROJECT_REPORT_RECIPIENTS
            project_primary = set()
            for recs in PROJECT_REPORT_RECIPIENTS.values():
                project_primary.update(recs)
            to_emails, cc_emails = compute_personal_recipients(
                member, exclude_from_cc=list(project_primary))
            print(f"\n  [PERSONAL] {member['name']} → to={to_emails} cc={cc_emails}")
            if args.dry_run:
                continue
            if send_personal_report_email(member, path, "周报",
                                          exclude_from_cc=list(project_primary)) and sent_log:
                sent_log.mark_sent(path, to_emails=to_emails, cc_emails=cc_emails,
                                    subject=f"【{member['name']}】",
                                    report_type="personal")

    print("\n" + "=" * 60)
    print("发送完成")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
