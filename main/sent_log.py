#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
已发送邮件记录（用于去重）

每个报告文件按 md5 内容签名做去重——文件被重新生成（内容变）就允许重发，
但同一份内容多次跑脚本只发 1 次。

记录位置：output/sent_log.json（与报告同目录，便于清理）
"""

import os
import json
import hashlib
from datetime import datetime
from typing import List, Dict, Optional


def _default_log_path() -> str:
    """默认 sent_log 路径：work_report/output/sent_log.json"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "output", "sent_log.json")


class SentLog:
    """已发送邮件记录

    签名规则：md5(file_content) 前 16 位 + 绝对路径
    → 文件内容不变 → 签名不变 → 跳过发送
    → 文件重新生成（内容变）→ 签名变 → 允许发送
    """

    def __init__(self, log_path: Optional[str] = None):
        self.log_path = log_path or _default_log_path()
        self._entries: List[Dict] = []
        self._load()

    # ---------- 持久化 ----------

    def _load(self):
        if not os.path.isfile(self.log_path):
            self._entries = []
            return
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._entries = data.get("entries", [])
        except (json.JSONDecodeError, OSError):
            # 损坏的 log 当作空（fail-safe）
            self._entries = []

    def _save(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "entries": self._entries,
            }, f, ensure_ascii=False, indent=2)

    # ---------- 签名 ----------

    @staticmethod
    def _signature(file_path: str) -> str:
        """文件签名：路径 + md5 前 16 位"""
        if not file_path or not os.path.isfile(file_path):
            return ""
        h = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                h.update(f.read())
        except OSError:
            return ""
        return f"{os.path.abspath(file_path)}|{h.hexdigest()[:16]}"

    # ---------- 查询 ----------

    def is_sent(self, file_path: str) -> bool:
        """检查文件内容是否已发过（基于签名）"""
        sig = self._signature(file_path)
        if not sig:
            return False
        return any(e.get("sig") == sig for e in self._entries)

    def get_entry(self, file_path: str) -> Optional[Dict]:
        """获取文件的发送记录"""
        sig = self._signature(file_path)
        for e in self._entries:
            if e.get("sig") == sig:
                return e
        return None

    # ---------- 写入 ----------

    def mark_sent(self, file_path: str, to_emails: List[str],
                  subject: str, report_type: str = "weekly",
                  cc_emails: Optional[List[str]] = None) -> None:
        """标记文件已发送"""
        sig = self._signature(file_path)
        if not sig:
            return
        # 幂等：同签名不重复添加
        if any(e.get("sig") == sig for e in self._entries):
            return
        self._entries.append({
            "sig": sig,
            "file_path": os.path.abspath(file_path),
            "sent_at": datetime.now().isoformat(timespec="seconds"),
            "to_emails": to_emails or [],
            "cc_emails": cc_emails or [],
            "subject": subject,
            "type": report_type,
        })
        self._save()

    def clear_file(self, file_path: str) -> bool:
        """清除单个文件的发送记录（强制重发用）"""
        sig = self._signature(file_path)
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.get("sig") != sig]
        removed = len(self._entries) < before
        if removed:
            self._save()
        return removed

    def clear_all(self) -> int:
        """清空所有发送记录，返回清理条数"""
        count = len(self._entries)
        self._entries = []
        self._save()
        return count

    # ---------- 列表 ----------

    def list(self) -> List[Dict]:
        return list(self._entries)


if __name__ == "__main__":
    # CLI：查看 / 清理
    import sys
    log = SentLog()
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "list":
            for e in log.list():
                print(f"  {e.get('sent_at', '?')} | {e.get('subject', '?')} | {e.get('file_path', '?')}")
        elif cmd == "clear":
            n = log.clear_all()
            print(f"清理 {n} 条记录")
        elif cmd == "check" and len(sys.argv) > 2:
            sent = log.is_sent(sys.argv[2])
            print(f"{'已发送' if sent else '未发送'}: {sys.argv[2]}")
        else:
            print("用法: python sent_log.py [list|clear|check <file>]")
    else:
        print(f"已发送记录: {len(log.list())} 条")
        print(f"位置: {log.log_path}")
