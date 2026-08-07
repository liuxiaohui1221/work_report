#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直接发送项目周报邮件"""

import sys
sys.path.insert(0, r"C:\workspace\pywork\work_report\main")

from email_sender import send_project_report_email

# 项目周报文件路径
# 2026-07-12 取消 platform 项目周报：删除 platform 周报发送
agent_report = r"C:\workspace\pywork\work_report\output\202606\20260601\by_project\Agent项目（cyber-agent）_周报_2026-06-08.md"

# 收件人
agent_recipients = ["liuxiaohui@datacyber.com"]

print("=" * 60)
print("开始发送项目周报邮件")
print("=" * 60)

# 发送Agent项目周报
print(f"\n[1] 发送Agent项目周报...")
result2 = send_project_report_email("Agent项目（cyber-agent）", agent_report, "周报", agent_recipients)
print(f"    结果: {'成功' if result2 else '失败'}")

print("\n" + "=" * 60)
print(f"邮件发送完成: Agent={'成功' if result2 else '失败'}")
print("=" * 60)