#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邮件发送模块
功能：发送报告邮件给指定收件人
"""

import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

from config import (
    EMAIL_ENABLED, EMAIL_SMTP_HOST, EMAIL_SMTP_PORT,
    EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD, EMAIL_FROM_NAME,
    TEAM_MEMBER_SEND_EMAIL, TEAM_MEMBER_EMAIL_MODE,
    EMAIL_RATE_LIMIT, EMAIL_RATE_PERIOD, PERSONAL_REPORT_RECIPIENT
)

# 全局发件人覆盖（用于交互式选择发件人后覆盖配置中的默认发件人）
_overridden_sender = None

# 邮件发送频率限制
_sent_count = 0
_sent_start_time = None


def reset_email_rate_limit():
    """重置邮件发送计数"""
    global _sent_count, _sent_start_time
    _sent_count = 0
    _sent_start_time = None


def check_email_rate_limit(limit: int, period: int) -> bool:
    """检查是否超过邮件发送频率限制

    Args:
        limit: 时间周期内最多发送数量
        period: 时间周期（秒）

    Returns:
        True 可以发送，False 超过限制
    """
    global _sent_count, _sent_start_time
    import time

    now = time.time()
    if _sent_start_time is None:
        _sent_start_time = now

    # 检查是否在周期内
    if now - _sent_start_time > period:
        # 超出周期，重置计数
        _sent_count = 0
        _sent_start_time = now

    if _sent_count >= limit:
        print(f"[WARN] 邮件发送频率超限，最多 {limit} 封/{period}秒")
        return False

    _sent_count += 1
    return True


def set_email_sender(email: str = None) -> None:
    """设置全局发件人覆盖值"""
    global _overridden_sender
    _overridden_sender = email


def confirm_email_sender_and_recipients(git_authors: list, default_sender: str,
                                        personal_recipients: list = None,
                                        project_recipients: list = None) -> tuple:
    """交互式确认收件人（发件人固定使用配置）

    Args:
        git_authors: Git作者列表（未使用，保留兼容性）
        default_sender: 默认发件人邮箱（来自配置）
        personal_recipients: 个人报告收件人列表
        project_recipients: 项目报告收件人列表

    Returns:
        tuple: (确认发送标志, 发件人邮箱, 收件人列表)
               如果用户取消返回 (False, None, None)
    """
    if not EMAIL_ENABLED:
        print("[INFO] 邮件发送已禁用")
        return False, None, None

    print("\n" + "=" * 60)
    print("邮件发送确认")
    print("=" * 60)

    # 发件人固定使用配置
    sender_email = default_sender
    sender_name = EMAIL_FROM_NAME

    # 显示邮件信息
    print(f"\n【邮件发送信息】")
    print(f"  发件人: {sender_name} <{sender_email}>")

    if personal_recipients:
        print(f"  个人报告收件人: {', '.join(personal_recipients)}")
    if project_recipients:
        print(f"  项目报告收件人: {', '.join(project_recipients)}")

    # 确认
    print()
    all_recipients = (personal_recipients or []) + (project_recipients or [])
    if not all_recipients:
        print("[WARN] 没有收件人，取消发送")
        return False, None, None

    confirm = input("确认发送以上邮件? (y/n): ").strip().lower()
    if confirm != 'y':
        print("[INFO] 用户取消发送")
        return False, None, None

    return True, sender_email, all_recipients


def send_email(subject: str, body: str, to_emails: list, attachments: list = None,
               from_email: str = None, from_name: str = None, cc_emails: list = None) -> bool:
    """发送邮件

    Args:
        subject: 邮件主题
        body: 邮件正文（HTML格式）
        to_emails: 收件人邮箱列表
        attachments: 附件文件路径列表（可选）
        from_email: 发件人邮箱（可选，默认使用全局覆盖值或配置中的EMAIL_SMTP_USER）
        from_name: 发件人显示名称（可选，默认使用EMAIL_FROM_NAME）
        cc_emails: 抄送收件人邮箱列表（可选）

    Returns:
        bool: 发送是否成功
    """
    global _overridden_sender

    if not EMAIL_ENABLED:
        print("[INFO] 邮件发送已禁用，跳过发送")
        return False

    if not to_emails:
        print("[WARN] 没有收件人，跳过发送")
        return False

    # 检查发送频率限制
    if not check_email_rate_limit(EMAIL_RATE_LIMIT, EMAIL_RATE_PERIOD):
        print("[WARN] 邮件发送频率超限，跳过发送")
        return False

    # 确定发件人：优先级：_overridden_sender > from_email > EMAIL_SMTP_USER
    actual_sender = _overridden_sender if _overridden_sender else (from_email or EMAIL_SMTP_USER)
    actual_name = from_name or EMAIL_FROM_NAME

    try:
        msg = MIMEMultipart()

        # 处理发件人昵称编码
        # 如果昵称包含非ASCII字符，需要用base64编码（RFC2047）
        def encode_sender_name(name: str, email: str) -> str:
            name_bytes = name.encode('utf-8')
            # 检查是否包含非ASCII字符
            try:
                name.encode('ascii')
                # 全ASCII，直接返回
                return f'"{name}" <{email}>'
            except UnicodeEncodeError:
                # 包含非ASCII字符，需要base64编码
                import base64
                encoded = base64.b64encode(name_bytes).decode('ascii')
                return f'=?UTF-8?B?{encoded}?= <{email}>'

        msg['From'] = encode_sender_name(actual_name, actual_sender)
        msg['To'] = ", ".join(to_emails)
        if cc_emails:
            msg['Cc'] = ", ".join(cc_emails)
        msg['Subject'] = subject
        msg['Date'] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0800")

        print(f"[DEBUG] 邮件From头: {msg['From']}", flush=True)
        print(f"[DEBUG] 邮件To头: {msg['To']}", flush=True)
        print(f"[DEBUG] 邮件Subject: {msg['Subject']}", flush=True)

        # 添加正文（HTML）
        msg.attach(MIMEText(body, 'html', 'utf-8'))

        # 发送邮件
        print(f"[DEBUG] 开始发送邮件, SMTP_USER={EMAIL_SMTP_USER}, to_emails={to_emails}, cc_emails={cc_emails}")
        if EMAIL_SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=30)
        else:
            server = smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=30)
            server.starttls()
        server.login(EMAIL_SMTP_USER, EMAIL_SMTP_PASSWORD)
        print(f"[DEBUG] 登录成功, 开始发送邮件...")
        all_recipients = to_emails + (cc_emails if cc_emails else [])
        server.sendmail(EMAIL_SMTP_USER, all_recipients, msg.as_string())
        server.quit()

        print(f"[OK] 邮件已发送至: {', '.join(to_emails)}{' (抄送: ' + ', '.join(cc_emails) + ')' if cc_emails else ''}")
        return True

    except smtplib.SMTPException as e:
        print(f"[ERROR] 邮件发送失败 (SMTP): {e}")
        return False
    except Exception as e:
        print(f"[ERROR] 邮件发送失败: {e}")
        return False


def build_email_body(report_name: str, report_content: str, date_desc: str) -> str:
    """构建邮件正文HTML

    Args:
        report_name: 报告名称
        report_content: 报告内容（Markdown格式，会转换为HTML显示）
        date_desc: 日期描述

    Returns:
        str: HTML格式的邮件正文
    """
    import re

    html_content = report_content

    # 转义HTML特殊字符
    html_content = html_content.replace('&', '&amp;')
    html_content = html_content.replace('<', '&lt;')
    html_content = html_content.replace('>', '&gt;')

    # 移除分隔线 --- 改为空行
    html_content = re.sub(r'^---+$', '', html_content, flags=re.MULTILINE)

    # 标题 - 缩小字号
    html_content = re.sub(r'^### (.+)$', r'<h4>\1</h4>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^## (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^# (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)

    # 列表
    html_content = re.sub(r'^- (.+)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^(\d+)\. (.+)$', r'<li>\1. \2</li>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'(<li>.*</li>\n)+', r'<ul>\g<0></ul>', html_content)

    # 粗体
    html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)

    # 代码块
    html_content = re.sub(r'```[\w]*\n(.+?)\n```', r'<pre><code>\1</code></pre>', html_content, flags=re.DOTALL)
    html_content = re.sub(r'`(.+?)`', r'<code>\1</code>', html_content)

    # 表格处理 - 将Markdown表格转换为HTML表格
    def convert_table(match):
        table_lines = match.group(0).strip().split('\n')
        if len(table_lines) < 2:
            return match.group(0)

        # 解析表头和对齐行
        header_line = table_lines[0]
        align_line = table_lines[1] if len(table_lines) > 1 else ""

        # 提取表头单元格
        headers = [h.strip() for h in header_line.split('|') if h.strip()]

        # 判断每列对齐方式
        aligns = []
        if '---:' in align_line:
            aligns = ['right'] * len(headers)
        elif ':---' in align_line:
            aligns = ['left'] * len(headers)
        else:
            aligns = ['center'] * len(headers)

        # 解析数据行
        rows = []
        for i in range(2, len(table_lines)):
            cells = [c.strip() for c in table_lines[i].split('|') if c.strip()]
            if cells:
                rows.append(cells)

        # 构建HTML表格
        html = '<table style="border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13px;">'
        html += '<thead><tr>'
        for i, h in enumerate(headers):
            align = aligns[i] if i < len(aligns) else 'left'
            html += f'<th style="border: 1px solid #ddd; padding: 8px 10px; text-align: {align}; background-color: #f5f5f5; font-weight: 600;">{h}</th>'
        html += '</tr></thead><tbody>'
        for row in rows:
            html += '<tr>'
            for i, cell in enumerate(row):
                align = aligns[i] if i < len(aligns) else 'left'
                html += f'<td style="border: 1px solid #ddd; padding: 6px 10px; text-align: {align};">{cell}</td>'
            html += '</tr>'
        html += '</tbody></table>'
        return html

    # 匹配整个表格（表头行、对齐行、一到多行数据行）
    html_content = re.sub(r'(\|.+\|\n\|[-| :]+\|\n(?:\|.+\|\n?)+)', convert_table, html_content)

    # 换行处理 - 保持单换行，双换行才是段落
    lines = html_content.split('\n')
    processed_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('<h') or line.startswith('<ul') or line.startswith('<pre'):
            processed_lines.append(line)
        elif line.startswith('<li'):
            processed_lines.append(line)
        else:
            processed_lines.append(f'<p style="margin: 5px 0;">{line}</p>')
    html_content = '\n'.join(processed_lines)

    # 移除开头的标题（只保留日期和正文）
    lines = html_content.split('\n')
    processed_lines = []
    skip_heading_count = 0
    for line in lines:
        # 跳过开头的连续标题（h2/h3/h4），最多跳过前3个
        if skip_heading_count < 3 and (line.startswith('<h2>') or line.startswith('<h3>') or line.startswith('<h4>')):
            skip_heading_count += 1
            continue
        processed_lines.append(line)
    html_content = '\n'.join(processed_lines)

    # 包装 - 简洁口语化
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.5; color: #333; max-width: 650px; margin: 0 auto; padding: 20px; font-size: 14px; }}
            h2 {{ color: #2c3e50; font-size: 16px; margin-bottom: 10px; }}
            h3 {{ color: #34495e; font-size: 14px; margin-top: 15px; margin-bottom: 8px; }}
            h4 {{ color: #555; font-size: 13px; margin-top: 12px; margin-bottom: 6px; }}
            p {{ margin: 4px 0; color: #444; }}
            ul {{ margin: 5px 0; padding-left: 18px; }}
            li {{ margin: 3px 0; color: #444; }}
            code {{ background-color: #f5f5f5; padding: 1px 4px; border-radius: 2px; font-size: 12px; }}
            pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 12px; }}
        </style>
    </head>
    <body>
        <h2>{report_name}</h2>
        <p style="color: #888; font-size: 12px;">{date_desc}</p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 10px 0;">
        <div>{html_content}</div>
    </body>
    </html>
    """
    return body


def select_recipients_from_git_authors(git_authors: list) -> list:
    """从Git作者列表中选择邮件收件人

    Args:
        git_authors: Git作者列表，每个元素包含 name, email, projects

    Returns:
        list: 选中的邮箱列表（如果用户取消返回空列表）
    """
    if not git_authors:
        print("[WARN] 没有Git作者可选")
        return []

    print("\n" + "=" * 60)
    print("选择发送个人报告的收件人")
    print("=" * 60)
    print("0. 不发送给任何人")
    for i, author in enumerate(git_authors, 1):
        projects = ", ".join(author.get("projects", []))
        print(f"{i}. {author['name']} <{author['email']}> (项目: {projects})")

    print("\n输入编号（用逗号分隔，如 1,3 或直接回车发送给全部）: ", end="")
    try:
        choice = input().strip()
        if choice == "0":
            return []
        if choice == "":
            # 回车发送给全部
            return [author['email'] for author in git_authors]
        indices = [int(x.strip()) - 1 for x in choice.split(",")]
        selected = [git_authors[i]['email'] for i in indices if 0 <= i < len(git_authors)]
        return selected
    except ValueError:
        print("[ERROR] 输入无效，返回全部")
        return [author['email'] for author in git_authors]


def select_project_report_recipients(project_name: str, project_members: list) -> list:
    """选择项目报告的收件人

    Args:
        project_name: 项目名称
        project_members: 该项目的所有成员列表

    Returns:
        list: 选中的邮箱列表（返回空列表表示跳过发送）
    """
    print("\n" + "=" * 60)
    print(f"选择 {project_name} 项目报告的收件人")
    print("=" * 60)
    print("0. 不发送给任何人")
    print("1. 发送给项目所有成员")
    for i, member in enumerate(project_members, 2):
        print(f"{i+1}. {member['name']} <{member['email']}>")

    print("\n输入编号（直接回车默认发送给所有成员）: ", end="")
    try:
        choice = input().strip()
        if choice == "0":
            return []
        if choice == "" or choice == "1":
            # 发送给所有成员
            return [member['email'] for member in project_members]
        # 选择特定成员
        idx = int(choice) - 2
        if 0 <= idx < len(project_members):
            return [project_members[idx]['email']]
        return [member['email'] for member in project_members]
    except ValueError:
        print("[INFO] 输入无效，发送给所有成员")
        return [member['email'] for member in project_members]
    """让用户选择要给哪些团队成员发送邮件

    Args:
        members: 团队成员列表

    Returns:
        list: 选中要发送邮件的成员列表（如果用户取消返回空列表）
    """
    if not members:
        print("[WARN] 没有团队成员")
        return []

    print("\n" + "=" * 60)
    print("选择发送个人报告的成员")
    print("=" * 60)
    print("0. 不发送给任何人")
    for i, member in enumerate(members, 1):
        projects = ", ".join(member.get("project_roles", {}).keys())
        print(f"{i}. {member['name']} <{member['email']}> (项目: {projects})")

    print("\n输入编号（用逗号分隔，如 1,3 或直接回车发送全部）: ", end="")
    try:
        choice = input().strip()
        if choice == "0":
            return []
        if choice == "":
            return members  # 直接回车发送给全部
        indices = [int(x.strip()) - 1 for x in choice.split(",")]
        selected = [members[i] for i in indices if 0 <= i < len(members)]
        return selected
    except ValueError:
        print("[ERROR] 输入无效，返回全部成员")
        return members


def send_personal_report_email(member: dict, report_path: str, report_type: str = "日报") -> bool:
    """发送个人报告邮件

    Args:
        member: 成员信息字典，包含 name, email 等
        report_path: 报告文件路径
        report_type: 报告类型（日报/周报）

    Returns:
        bool: 发送是否成功
    """
    if not EMAIL_ENABLED or not TEAM_MEMBER_SEND_EMAIL:
        return False

    if not os.path.exists(report_path):
        print(f"[WARN] 报告文件不存在: {report_path}")
        return False

    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            report_content = f.read()

        # 提取文件名中的日期和日期范围描述
        import re
        date_match = re.search(r'_(\d{4}-\d{2}-\d{2})_', report_path)
        date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")
        # 从文件名提取日期范围描述，如"最近2天"、"今天"、"昨天"
        desc_match = re.search(r'_(\d{4}-\d{2}-\d{2})_(.+?)\.md$', report_path)
        date_desc = desc_match.group(2) if desc_match else ""

        report_name = f"{member['name']}工作{report_type}"
        # 邮件标题简洁明了
        subject = f"【{member['name']}】{date_str} {date_desc}"

        body = build_email_body(report_name, report_content, date_str)

        to_emails = [member['email']]
        # 如果配置了上级收件人，添加到抄送列表（去重，避免和to_emails重复）
        cc_emails = []
        if PERSONAL_REPORT_RECIPIENT:
            cc_list = PERSONAL_REPORT_RECIPIENT if isinstance(PERSONAL_REPORT_RECIPIENT, list) else [PERSONAL_REPORT_RECIPIENT]
            cc_emails = [e for e in cc_list if e != member['email']]
        result = send_email(subject, body, to_emails, attachments=[report_path], cc_emails=cc_emails)

        return result

    except Exception as e:
        print(f"[ERROR] 发送个人报告邮件失败: {e}")
        return False


def send_project_report_email(project_name: str, report_path: str, report_type: str = "日报",
                               to_emails: list = None) -> bool:
    """发送项目报告邮件

    Args:
        project_name: 项目名称
        report_path: 报告文件路径
        report_type: 报告类型（日报/周报）
        to_emails: 收件人邮箱列表，如果为 None 则不发送

    Returns:
        bool: 发送是否成功
    """
    if not EMAIL_ENABLED:
        return False

    if to_emails is None or len(to_emails) == 0:
        print("[INFO] 没有配置项目报告收件人，跳过发送")
        return False

    if not os.path.exists(report_path):
        print(f"[WARN] 报告文件不存在: {report_path}")
        return False

    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            report_content = f.read()

        # 提取文件名中的日期和日期范围描述
        import re
        date_match = re.search(r'_(\d{4}-\d{2}-\d{2})_', report_path)
        date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")
        # 从文件名提取日期范围描述，如"最近2天"、"今天"、"昨天"
        desc_match = re.search(r'_(\d{4}-\d{2}-\d{2})_(.+?)\.md$', report_path)
        date_desc = desc_match.group(2) if desc_match else ""

        report_name = project_name
        # 邮件标题简洁明了
        subject = f"【项目进度】{project_name} {date_str} {date_desc}"

        body = build_email_body(report_name, report_content, date_str)

        result = send_email(subject, body, to_emails, attachments=[report_path])

        return result

    except Exception as e:
        print(f"[ERROR] 发送项目报告邮件失败: {e}")
        return False