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


# 4 段卡片样式常量（QQ Mail / Gmail / Outlook / 企业微信邮箱均支持）
RICH_EMAIL_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        line-height: 1.6; color: #1f2937; max-width: 720px; margin: 0 auto; padding: 20px; background: #ffffff; font-size: 14px; }
.header { border-bottom: 2px solid #e5e7eb; padding-bottom: 12px; margin-bottom: 20px; }
.header h1 { margin: 0 0 4px 0; font-size: 20px; color: #1e3a8a; }
.header .meta { color: #6b7280; font-size: 13px; }
.section { background: #f8fafc; border-left: 4px solid #3b82f6; border-radius: 4px;
           padding: 14px 18px; margin: 14px 0; }
.section h3 { margin: 0 0 10px 0; color: #1e40af; font-size: 15px; font-weight: 600; }
.section.summary { border-left-color: #10b981; }
.section.summary h3 { color: #047857; }
.section.plan { border-left-color: #8b5cf6; }
.section.plan h3 { color: #6d28d9; }
.section.help { border-left-color: #f59e0b; background: #fffbeb; }
.section.help h3 { color: #b45309; }
.item { padding: 8px 0; border-bottom: 1px solid #e5e7eb; line-height: 1.5; }
.item:last-child { border-bottom: none; }
.item .src { color: #9ca3af; font-size: 12px; margin-left: 6px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
         font-size: 11px; font-weight: 600; margin-right: 6px; vertical-align: middle; }
.badge-done { background: #d1fae5; color: #065f46; }
.badge-progress { background: #dbeafe; color: #1e40af; }
.badge-blocked { background: #fee2e2; color: #991b1b; }
.badge-todo { background: #ede9fe; color: #5b21b6; }
.status { display: inline-block; padding: 4px 14px; border-radius: 16px;
          font-weight: 600; font-size: 13px; }
.status-green { background: #d1fae5; color: #065f46; }
.status-yellow { background: #fef3c7; color: #92400e; }
.status-red { background: #fee2e2; color: #991b1b; }
.progress-bar { background: #e5e7eb; height: 8px; border-radius: 4px;
                overflow: hidden; margin: 8px 0; }
.progress-fill { background: linear-gradient(90deg, #10b981, #34d399);
                 height: 100%; border-radius: 4px; }
.appendix { margin-top: 28px; padding-top: 14px; border-top: 1px dashed #d1d5db; }
.appendix h4 { margin: 0 0 10px 0; color: #6b7280; font-size: 13px; font-weight: 500; }
.appendix ul { margin: 0; padding-left: 18px; }
.appendix li { padding: 3px 0; color: #4b5563; font-size: 12px; }
.appendix a { color: #2563eb; text-decoration: none; }
code { background: #f1f5f9; padding: 1px 6px; border-radius: 3px;
       font-size: 12px; color: #be185d; font-family: 'SF Mono', Consolas, monospace; }
strong { color: #1f2937; }
"""


def _html_escape(text: str) -> str:
    """转义 HTML 特殊字符"""
    return (text.replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;'))


def _render_markdown_inline(text: str) -> str:
    """渲染 markdown 行内语法：**bold**、`code`、link"""
    import re
    # 链接 [text](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  r'<a href="\2" style="color:#2563eb;text-decoration:none;">\1</a>', text)
    # 加粗 **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # 行内代码 `code`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text


def _auto_badge(item_text: str, section: str = "done") -> str:
    """根据条目文本 + section 类型自动分配状态徽章

    section='plan' 时强制 TODO（计划项不是已完成）
    其他 section 按关键词匹配：调研/规划→PROG，完成/修复→DONE，阻塞→BLOCKED
    """
    if section == "plan":
        # 计划项强制 TODO，无论关键词
        if '暂无' in item_text or item_text.strip() == '无':
            return '<span class="badge badge-done">✓ 无</span>'
        return '<span class="badge badge-todo">TODO</span>'
    lower = item_text.lower()
    if '暂无' in item_text or item_text.strip() == '无':
        return '<span class="badge badge-done">✓ 无</span>'
    if '调研' in item_text or '预研' in item_text or '规划' in item_text or '选型' in item_text:
        return '<span class="badge badge-progress">PROG</span>'
    if '完成' in item_text or '修复' in item_text or '迁移' in item_text or '落地' in item_text:
        return '<span class="badge badge-done">DONE</span>'
    if 'TODO' in item_text or 'todo' in lower:
        return '<span class="badge badge-todo">TODO</span>'
    if '阻塞' in item_text or '失败' in item_text or '异常' in item_text:
        return '<span class="badge badge-blocked">BLOCKED</span>'
    return '<span class="badge badge-progress">PROG</span>'


def _split_source(text: str) -> tuple:
    """把条目文本拆成 (主体内容, 来源标注)"""
    import re
    m = re.search(r'（来源[:：]?\s*(.+?)）', text)
    if m:
        return text[:m.start()].rstrip(), m.group(1)
    return text, None


def _parse_4section(markdown: str) -> dict:
    """解析 4 段式 markdown → {section_name: items}"""
    import re
    sections = {'done': [], 'summary': '', 'plan': [], 'help': []}
    current = None
    for line in markdown.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r'^#{2,3}\s*([一二三四])[、\.]\s*(.+)$', s)
        if m:
            key = {'一': 'done', '二': 'summary', '三': 'plan', '四': 'help'}[m.group(1)]
            if key == 'summary':
                sections['summary'] = ''
                current = 'summary'
            else:
                current = key
            continue
        if s.startswith('## 📌') or s.startswith('## 📌'):
            current = 'appendix'
            continue
        if current == 'summary':
            sections['summary'] = sections['summary'] + ('<br>' if sections['summary'] else '') + s
        elif current in ('done', 'plan', 'help'):
            if s.startswith(('- ', '* ')):
                sections[current].append(s[2:].strip())
    return sections


def build_email_body(report_name: str, report_content: str, date_desc: str) -> str:
    """构建邮件正文HTML（4 段卡片 + 状态徽章 + 进度条 + 协调警告框）

    自动识别 4 段式（一/二/三/四）结构并渲染成富 HTML 卡片。
    如果不是 4 段式（罕见），降级为基础 markdown 渲染。

    Args:
        report_name: 报告名称（如"刘小辉 周报"）
        report_content: 报告内容（Markdown）
        date_desc: 日期描述

    Returns:
        str: HTML 格式邮件正文
    """
    import re

    # 把 commit 附录（## 📌 本周提交清单）从主内容里分离
    appendix_match = re.search(r'(##\s*📌.*)', report_content, re.DOTALL)
    main_content = report_content
    appendix_md = ''
    if appendix_match:
        main_content = report_content[:appendix_match.start()].rstrip()
        appendix_md = report_content[appendix_match.start():]

    # 4 段式检测
    section_pattern = re.compile(r'^#{2,3}\s*[一二三四][、\.]', re.MULTILINE)
    has_4section = bool(section_pattern.search(main_content))

    if not has_4section:
        return _build_plain_email_body(report_name, report_content, date_desc)

    # 4 段式：富渲染
    sections = _parse_4section(main_content)

    # 状态灯
    status_match = re.search(r'(🟢|🟡|🔴)', sections['summary'])
    status_emoji = status_match.group(1) if status_match else '🟡'
    status_class = {'🟢': 'status-green', '🟡': 'status-yellow', '🔴': 'status-red'}[status_emoji]
    status_text = {'🟢': '正常', '🟡': '部分完成', '🔴': '阻塞'}[status_emoji]
    # 进度条按状态推断
    progress_pct = {'🟢': 100, '🟡': 60, '🔴': 25}[status_emoji]

    # 渲染完成工作项
    def render_items(items, kind='done'):
        if not items:
            return '<div class="item" style="color:#9ca3af;">（无）</div>'
        out = []
        for it in items:
            badge = _auto_badge(it, section=kind) if kind in ('done', 'plan', 'help') else ''
            main, src = _split_source(it)
            main_html = _html_escape(main)
            main_html = _render_markdown_inline(main_html)
            src_html = f'<span class="src">（来源：{_html_escape(src)}）</span>' if src else ''
            out.append(f'<div class="item">{badge}{main_html}{src_html}</div>')
        return '\n'.join(out)

    summary_html = _render_markdown_inline(_html_escape(sections['summary']))

    # 提交清单 HTML
    appendix_html = ''
    if appendix_md:
        items = []
        for line in appendix_md.splitlines():
            s = line.strip()
            if s.startswith(('- ', '* ')):
                items.append(s[2:].strip())
            elif s.startswith('##'):
                continue
        if items:
            lis = '\n'.join(f'<li>{_render_markdown_inline(_html_escape(it))}</li>' for it in items)
            appendix_html = f'''
<div class="appendix">
  <h4>📌 本周提交清单（追溯用）</h4>
  <ul>{lis}</ul>
</div>'''

    body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>{RICH_EMAIL_CSS}</style>
</head><body>
<div class="header">
  <h1>📊 {report_name}</h1>
  <div class="meta">{date_desc} · 周报</div>
</div>

<div class="section">
  <h3>📌 一、本周完成工作</h3>
  {render_items(sections['done'], 'done')}
</div>

<div class="section summary">
  <h3>📈 二、本周总结</h3>
  <p>{summary_html}</p>
  <p><span class="status {status_class}">{status_emoji} {status_text}</span></p>
  <div class="progress-bar"><div class="progress-fill" style="width: {progress_pct}%;"></div></div>
</div>

<div class="section plan">
  <h3>🗓️ 三、下周工作计划</h3>
  {render_items(sections['plan'], 'plan')}
</div>

<div class="section help">
  <h3>⚠️ 四、需协调与帮助</h3>
  {render_items(sections['help'], 'help')}
</div>
{appendix_html}
</body></html>"""
    return body


def _build_plain_email_body(report_name: str, report_content: str, date_desc: str) -> str:
    """降级版：4 段式识别失败时使用，保留基础 markdown 渲染"""
    import re

    html_content = report_content
    html_content = html_content.replace('&', '&amp;')
    html_content = html_content.replace('<', '&lt;')
    html_content = html_content.replace('>', '&gt;')
    html_content = re.sub(r'^---+$', '', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^### (.+)$', r'<h4>\1</h4>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^## (.+)$', r'<h3>\1</h3>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^# (.+)$', r'<h2>\1</h2>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^- (.+)$', r'<li>\1</li>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'^(\d+)\. (.+)$', r'<li>\1. \2</li>', html_content, flags=re.MULTILINE)
    html_content = re.sub(r'(<li>.*</li>\n)+', r'<ul>\g<0></ul>', html_content)
    html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)
    html_content = re.sub(r'```[\w]*\n(.+?)\n```', r'<pre><code>\1</code></pre>', html_content, flags=re.DOTALL)
    html_content = re.sub(r'`(.+?)`', r'<code>\1</code>', html_content)

    body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                line-height: 1.5; color: #333; max-width: 650px; margin: 0 auto; padding: 20px; font-size: 14px; }}
        h2 {{ color: #2c3e50; font-size: 16px; margin-bottom: 10px; }}
        h3 {{ color: #34495e; font-size: 14px; margin-top: 15px; margin-bottom: 8px; }}
        h4 {{ color: #555; font-size: 13px; margin-top: 12px; margin-bottom: 6px; }}
        p {{ margin: 4px 0; color: #444; }}
        ul {{ margin: 5px 0; padding-left: 18px; }}
        li {{ margin: 3px 0; color: #444; }}
        code {{ background-color: #f5f5f5; padding: 1px 4px; border-radius: 2px; font-size: 12px; }}
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


def compute_personal_recipients(member: dict, exclude_from_cc: list = None):
    """计算个人周报的收件人/抄送列表

    Args:
        member: 成员信息
        exclude_from_cc: 排除的邮箱（这些人已经是项目主收件人，避免重复邮件）

    Returns:
        (to_emails, cc_emails) 元组
    """
    to_emails = [member['email']]
    cc_emails = []
    if PERSONAL_REPORT_RECIPIENT:
        cc_list = PERSONAL_REPORT_RECIPIENT if isinstance(PERSONAL_REPORT_RECIPIENT, list) else [PERSONAL_REPORT_RECIPIENT]
        excluded = set(exclude_from_cc or [])
        cc_emails = [e for e in cc_list if e != member['email'] and e not in excluded]
    return to_emails, cc_emails


def send_personal_report_email(member: dict, report_path: str, report_type: str = "日报",
                                exclude_from_cc: list = None, subject_prefix: str = "") -> bool:
    """发送个人报告邮件

    Args:
        member: 成员信息字典，包含 name, email 等
        report_path: 报告文件路径
        report_type: 报告类型（日报/周报）
        exclude_from_cc: 排除的 CC 邮箱列表（避免和项目主收件人重复）
        subject_prefix: 主题前缀（测试模式加 [测试] 等）

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

        # 2026-08-08 邮件标题改为 {member_name}周报 格式
        report_name = f"{member['name']}周报"
        # 邮件标题简洁明了
        subject = f"{subject_prefix}【{member['name']}周报】{date_str} {date_desc}".strip()

        body = build_email_body(report_name, report_content, date_str)

        to_emails, cc_emails = compute_personal_recipients(member, exclude_from_cc)
        if exclude_from_cc and cc_emails:
            removed = set(exclude_from_cc) & set(PERSONAL_REPORT_RECIPIENT or [])
            if removed:
                print(f"[INFO] 个人周报 CC 去重，排除 {len(removed)} 个项目主收件人: {', '.join(removed)}")
        result = send_email(subject, body, to_emails, attachments=[report_path], cc_emails=cc_emails)

        return result

    except Exception as e:
        print(f"[ERROR] 发送个人报告邮件失败: {e}")
        return False


def send_project_report_email(project_name: str, report_path: str, report_type: str = "日报",
                               to_emails: list = None, subject_prefix: str = "") -> bool:
    """发送项目报告邮件

    Args:
        project_name: 项目名称
        report_path: 报告文件路径
        report_type: 报告类型（日报/周报）
        to_emails: 收件人邮箱列表，如果为 None 则不发送
        subject_prefix: 主题前缀（测试模式加 [测试] 等）

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

        # 2026-08-08 邮件标题改为 {project_name}项目周报 格式
        report_name = f"{project_name}项目周报"
        # 邮件标题简洁明了
        subject = f"{subject_prefix}【{project_name}项目周报】{date_str} {date_desc}".strip()

        body = build_email_body(report_name, report_content, date_str)

        result = send_email(subject, body, to_emails, attachments=[report_path])

        return result

    except Exception as e:
        print(f"[ERROR] 发送项目报告邮件失败: {e}")
        return False