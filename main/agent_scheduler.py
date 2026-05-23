#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能体定时调度器 - 定时运行各智能体任务并推送结果
"""

import os
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from main.agents import AgentScheduler, ProjectManagerAgent, call_llm
from main.models import (
    get_db_connection, ProjectDAO, DeveloperDAO, MessageDAO, BugDAO
)


class AgentSchedulerService:
    """智能体调度服务"""

    def __init__(self):
        self.scheduler = AgentScheduler()
        self.running = False
        self.thread = None
        self.last_run = {}

    def start(self):
        """启动调度器"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print("[AgentScheduler] Started")

    def stop(self):
        """停止调度器"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("[AgentScheduler] Stopped")

    def _run_loop(self):
        """调度循环"""
        while self.running:
            now = datetime.now()

            # 每小时检查一次
            self._check_and_run_agents(now)

            # 睡60秒再检查
            time.sleep(60)

    def _check_and_run_agents(self, now: datetime):
        """检查并运行智能体"""
        # 早上9点运行日报
        if now.hour == 9 and now.minute < 10:
            key = f"daily_report_{now.date()}"
            if key not in self.last_run:
                self._run_daily_reports()
                self.last_run[key] = now

        # 每30分钟运行进度追踪
        key = f"progress_{now.date()}_{now.hour}_{now.minute // 30}"
        if key not in self.last_run:
            self._run_progress_tracking()
            self.last_run[key] = now

    def _run_daily_reports(self):
        """运行每日报告"""
        print(f"[{datetime.now()}] 开始生成每日报告...")

        try:
            results = self.scheduler.daily_report_all_projects()

            for project_id, result in results.items():
                if 'error' in result:
                    print(f"项目{project_id}报告生成失败: {result['error']}")
                else:
                    print(f"项目{project_id}报告生成完成")

        except Exception as e:
            print(f"生成日报异常: {e}")

    def _run_progress_tracking(self):
        """运行进度追踪"""
        print(f"[{datetime.now()}] 运行进度追踪...")

        try:
            projects = ProjectDAO.get_all()

            for project in projects:
                try:
                    result = self.scheduler.run_project_agent(
                        'progress_tracker',
                        project['id']
                    )

                    # 检测到阻塞任务，发送通知
                    for r in result.get('results', []):
                        if 'blocked_tasks' in str(r):
                            blocked = r.get('blocked_tasks', [])
                            for task in blocked:
                                if task.get('assignee_id'):
                                    MessageDAO.create(
                                        msg_type='warning',
                                        title='🚧 任务被阻塞提醒',
                                        content=f'您的任务「{task["title"]}」被阻塞，请联系负责人尽快完成前置任务',
                                        receiver_id=task['assignee_id'],
                                        related_task_id=task.get('id')
                                    )

                except Exception as e:
                    print(f"项目{project['id']}进度追踪异常: {e}")

        except Exception as e:
            print(f"进度追踪异常: {e}")


# 全局调度器实例
_scheduler: Optional[AgentSchedulerService] = None


def get_scheduler() -> AgentSchedulerService:
    """获取调度器实例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = AgentSchedulerService()
    return _scheduler


def start_scheduler():
    """启动调度器（供Flask调用）"""
    scheduler = get_scheduler()
    scheduler.start()


def stop_scheduler():
    """停止调度器"""
    global _scheduler
    if _scheduler:
        _scheduler.stop()


# ========== 手动触发智能体 ==========

def trigger_agent(agent_name: str, project_id: int, action: str = None) -> Dict:
    """手动触发智能体"""
    scheduler = get_scheduler()
    return scheduler.run_project_agent(agent_name, project_id, action)


# ========== 主函数（测试用） ==========

if __name__ == '__main__':
    # 测试运行
    scheduler = AgentSchedulerService()

    # 运行所有项目的进度追踪
    print("开始测试智能体...")

    projects = ProjectDAO.get_all()
    for project in projects:
        print(f"\n处理项目: {project['name']}")

        # 项目经理生成报告
        result = scheduler.run_project_agent(
            'project_manager',
            project['id'],
            action='daily_report'
        )

        if 'report' in result:
            print(result['report'][:500])

    print("\n测试完成")