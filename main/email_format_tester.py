#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邮件格式测试工具

专门用于测试周报邮件格式的工具类。**默认只发送给 liuxiaohui 本人**（不抄送其他收件人），
方便在格式迭代时反复测试不同排版，不污染其他人邮箱。

功能：
- 加载本地周报文件（.md）作为测试内容
- 渲染成与正式周报一致的 HTML 邮件正文
- 发送到 liuxiaohui@datacyber.com
- 支持纯预览（不实际发送），方便先看效果
- 支持 A/B 两种格式对比（--variant=old|new|markdown|plain）

用法：
    # 方式 1：测试某个 .md 文件的渲染
    python email_format_tester.py --file output/202608/20260803/by_person/xiaohui_周报_2026-08-07.md

    # 方式 2：只预览不发送
    python email_format_tester.py --file xxx.md --preview

    # 方式 3：直接传文本
    python email_format_tester.py --content "## 标题\n正文"

    # 方式 4：A/B 对比（发两封，主题加 [A] [B] 前缀）
    python email_format_tester.py --file xxx.md --variant new --ab
"""

import os
import sys
import argparse
from datetime import datetime
from typing import Optional

# 把 main/ 加入 path，便于 import 兄弟模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from email_sender import build_email_body, send_email
from config import EMAIL_ENABLED, EMAIL_SMTP_USER, EMAIL_FROM_NAME


# 默认收件人：只发给 liuxiaohui 本人，不抄送
DEFAULT_TEST_RECIPIENT = "liuxiaohui@datacyber.com"


class EmailFormatTester:
    """邮件格式测试器

    默认行为：只发送给 liuxiaohui 本人，不抄送。
    所有方法都不会修改原周报文件，只会渲染预览或发送测试邮件。
    """

    def __init__(self, to_email: str = DEFAULT_TEST_RECIPIENT,
                 subject_prefix: str = "[格式测试]"):
        self.to_email = to_email
        self.subject_prefix = subject_prefix

    def _build_subject(self, raw_subject: str, variant: str = None) -> str:
        """构造测试邮件主题，加前缀方便识别"""
        parts = [self.subject_prefix]
        if variant:
            parts.append(f"[{variant}]")
        parts.append(raw_subject)
        return " ".join(parts)

    def preview(self, content: str, date_desc: str = "") -> str:
        """预览邮件正文的 HTML 渲染结果（不发送）"""
        if not date_desc:
            date_desc = datetime.now().strftime("%Y-%m-%d %H:%M")
        return build_email_body("格式测试预览", content, date_desc)

    def send(self, content: str, subject: str,
             variant: str = None, date_desc: str = None) -> bool:
        """发送测试邮件到 liuxiaohui（不抄送其他收件人）"""
        if not EMAIL_ENABLED:
            print("[WARN] 邮件发送已禁用 (EMAIL_ENABLED=False)")
            return False
        if not content.strip():
            print("[ERROR] 邮件内容为空，跳过发送")
            return False

        if not date_desc:
            date_desc = datetime.now().strftime("%Y-%m-%d %H:%M")

        full_subject = self._build_subject(subject, variant)
        body = build_email_body(subject, content, date_desc)

        print(f"\n[TEST] 准备发送测试邮件")
        print(f"  收件人: {self.to_email}（仅本人，不抄送）")
        print(f"  主题:   {full_subject}")
        print(f"  字数:   {len(content)} 字符")
        print()

        return send_email(
            subject=full_subject,
            body=body,
            to_emails=[self.to_email],
            cc_emails=None,  # 关键：不抄送
            from_email=EMAIL_SMTP_USER,
            from_name=EMAIL_FROM_NAME,
        )

    def send_from_file(self, file_path: str, subject: str = None,
                       variant: str = None) -> bool:
        """从 .md 文件读取内容并发送测试邮件"""
        if not os.path.isfile(file_path):
            print(f"[ERROR] 文件不存在: {file_path}")
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"[ERROR] 读取文件失败: {e}")
            return False
        if not subject:
            subject = os.path.basename(file_path)
        print(f"[OK] 已加载: {file_path} ({len(content)} 字符)")
        return self.send(content, subject, variant=variant)

    def send_ab(self, content_a: str, content_b: str,
                subject: str = "A/B 格式对比") -> bool:
        """A/B 格式对比：发两封邮件，分别加 [A] [B] 前缀"""
        print("\n=== A/B 格式对比 ===\n")
        ok_a = self.send(content_a, subject, variant="A")
        print()
        ok_b = self.send(content_b, subject, variant="B")
        return ok_a and ok_b


def main():
    parser = argparse.ArgumentParser(
        description="邮件格式测试工具（默认只发给 liuxiaohui 本人）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--file", "-f", help="要测试的 .md 文件路径")
    parser.add_argument("--content", "-c", help="直接传文本内容（与 --file 二选一）")
    parser.add_argument("--subject", "-s", default="周报格式测试",
                        help="邮件主题（默认：周报格式测试）")
    parser.add_argument("--to", default=DEFAULT_TEST_RECIPIENT,
                        help=f"收件人邮箱（默认：{DEFAULT_TEST_RECIPIENT}）")
    parser.add_argument("--preview", "-p", action="store_true",
                        help="只预览 HTML 渲染结果，不发送")
    parser.add_argument("--variant", "-v",
                        help="格式变体标识，会加到主题前缀（例：old / new / markdown）")
    parser.add_argument("--save-html", help="保存渲染的 HTML 到指定路径")
    parser.add_argument("--ab", action="store_true",
                        help="A/B 模式：内容字段会被当作 A，文件字段当作 B")

    args = parser.parse_args()

    tester = EmailFormatTester(to_email=args.to)

    if not args.file and not args.content:
        parser.print_help()
        return 1

    # A/B 模式
    if args.ab:
        if not (args.content and args.file):
            print("[ERROR] A/B 模式需要同时传 --content (A) 和 --file (B)")
            return 1
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                content_b = f.read()
        except Exception as e:
            print(f"[ERROR] 读取 B 文件失败: {e}")
            return 1
        ok = tester.send_ab(args.content, content_b, subject=args.subject)
        return 0 if ok else 1

    # 单次发送或预览
    if args.file:
        if not os.path.isfile(args.file):
            print(f"[ERROR] 文件不存在: {args.file}")
            return 1
        with open(args.file, "r", encoding="utf-8") as f:
            content = f.read()
        print(f"[OK] 已加载: {args.file} ({len(content)} 字符)")
    else:
        content = args.content

    if args.preview:
        html = tester.preview(content)
        if args.save_html:
            with open(args.save_html, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[OK] HTML 已保存: {args.save_html}")
        else:
            print("\n" + "=" * 60)
            print("HTML 预览（前 3000 字符）")
            print("=" * 60)
            print(html[:3000])
            if len(html) > 3000:
                print(f"\n... (已截断，共 {len(html)} 字符，用 --save-html 保存完整版)")
        return 0

    ok = tester.send(content, args.subject, variant=args.variant)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
