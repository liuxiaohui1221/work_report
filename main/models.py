#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据模型层 - 任务管理、项目进度、智能体系统
"""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager


# 数据库路径
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work_report.db")


@contextmanager
def get_db_connection():
    """获取数据库连接的上下文管理器"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


class TaskDAO:
    """任务数据访问对象"""

    @staticmethod
    def create(project_id: int, title: str, description: str = None,
               status: str = '待认领', priority: str = '中',
               assignee_id: int = None, reporter_id: int = None,
               due_date: str = None, depends_on: int = None,
               module: str = None) -> int:
        """创建新任务"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pm_tasks
                (project_id, title, description, status, priority, module,
                 assignee_id, reporter_id, due_date, depends_on)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (project_id, title, description, status, priority, module,
                  assignee_id, reporter_id, due_date, depends_on))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(task_id: int) -> Optional[Dict]:
        """根据ID获取任务"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT t.*, p.name as project_name,
                       a.name as assignee_name, a.email as assignee_email,
                       r.name as reporter_name
                FROM pm_tasks t
                LEFT JOIN pm_projects p ON t.project_id = p.id
                LEFT JOIN pm_developers a ON t.assignee_id = a.id
                LEFT JOIN pm_developers r ON t.reporter_id = r.id
                WHERE t.id = ?
            ''', (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_project(project_id: int, status: str = None,
                       assignee_id: int = None) -> List[Dict]:
        """获取项目的任务列表"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT t.*, p.name as project_name,
                       a.name as assignee_name, a.email as assignee_email,
                       r.name as reporter_name,
                       d.title as depends_on_title, d.status as depends_on_status
                FROM pm_tasks t
                LEFT JOIN pm_projects p ON t.project_id = p.id
                LEFT JOIN pm_developers a ON t.assignee_id = a.id
                LEFT JOIN pm_developers r ON t.reporter_id = r.id
                LEFT JOIN pm_tasks d ON t.depends_on = d.id
                WHERE t.project_id = ?
            '''
            params = [project_id]

            if status:
                query += ' AND t.status = ?'
                params.append(status)

            if assignee_id:
                query += ' AND t.assignee_id = ?'
                params.append(assignee_id)

            query += ' ORDER BY t.priority DESC, t.due_date ASC'

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_assignee(assignee_id: int, project_id: int = None, include_blocked: bool = True) -> List[Dict]:
        """获取分配给某人的任务"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT t.*, p.name as project_name,
                       d.title as depends_on_title, d.status as depends_on_status,
                       d.assignee_name as blocked_by_name
                FROM pm_tasks t
                LEFT JOIN pm_projects p ON t.project_id = p.id
                LEFT JOIN (
                    SELECT t2.id, t2.title, t2.status,
                           a.name as assignee_name
                    FROM pm_tasks t2
                    LEFT JOIN pm_developers a ON t2.assignee_id = a.id
                ) d ON t.depends_on = d.id
                WHERE t.assignee_id = ?
            '''

            if project_id:
                query += ' AND t.project_id = ?'
                params = (assignee_id, project_id)
            else:
                params = (assignee_id,)

            if not include_blocked:
                query += ' AND t.status != "被阻塞"'

            query += ' ORDER BY t.status, t.priority DESC, t.due_date ASC'

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def update(task_id: int, **kwargs) -> bool:
        """更新任务"""
        allowed_fields = ['title', 'description', 'status', 'priority',
                         'module', 'assignee_id', 'due_date', 'depends_on',
                         'progress', 'tags']
        updates = []
        params = []

        for key, value in kwargs.items():
            if key in allowed_fields and value is not None:
                updates.append(f"{key} = ?")
                params.append(value)

        if not updates:
            return False

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(task_id)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE pm_tasks SET {', '.join(updates)} WHERE id = ?
            ''', params)
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def delete(task_id: int) -> bool:
        """删除任务"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # 先删除关联的历史记录
            cursor.execute('DELETE FROM pm_task_history WHERE task_id = ?', (task_id,))
            cursor.execute('DELETE FROM pm_tasks WHERE id = ?', (task_id,))
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def get_blocked_tasks(project_id: int = None) -> List[Dict]:
        """获取被阻塞的任务（前置任务未完成）"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT t.*, p.name as project_name,
                       d.title as depends_on_title, d.status as depends_on_status,
                       a.name as assignee_name
                FROM pm_tasks t
                LEFT JOIN pm_projects p ON t.project_id = p.id
                LEFT JOIN pm_tasks d ON t.depends_on = d.id
                LEFT JOIN pm_developers a ON t.assignee_id = a.id
                WHERE t.status != '已完成'
                  AND d.status != '已完成'
                  AND d.status IS NOT NULL
            '''
            params = []
            if project_id:
                query += ' AND t.project_id = ?'
                params.append(project_id)
            query += ' ORDER BY t.priority DESC'

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_my_blockers(assignee_id: int, project_id: int = None) -> List[Dict]:
        """获取阻塞我工作的任务（前置任务）"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT t.*, p.name as project_name,
                       a.name as blocker_name, a.email as blocker_email
                FROM pm_tasks t
                LEFT JOIN pm_projects p ON t.project_id = p.id
                LEFT JOIN pm_developers a ON t.assignee_id = a.id
                WHERE t.id IN (
                    SELECT depends_on FROM pm_tasks
                    WHERE assignee_id = ? AND status NOT IN ('已完成', '被阻塞')
                )
                AND t.status NOT IN ('已完成', '待联调', '测试中', '已完成')
            '''

            if project_id:
                query += ' AND t.project_id = ?'
                params = (assignee_id, project_id)
            else:
                params = (assignee_id,)

            query += ' ORDER BY t.priority DESC'

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]


class TaskHistoryDAO:
    """任务历史记录数据访问对象"""

    @staticmethod
    def add(task_id: int, field_name: str, old_value: str, new_value: str,
            changed_by: int = None, reason: str = None) -> int:
        """添加历史记录"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pm_task_history
                (task_id, field_name, old_value, new_value, changed_by, change_reason)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (task_id, field_name, old_value, new_value, changed_by, reason))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_task(task_id: int) -> List[Dict]:
        """获取任务的历史记录"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT h.*, d.name as changed_by_name
                FROM pm_task_history h
                LEFT JOIN pm_developers d ON h.changed_by = d.id
                WHERE h.task_id = ?
                ORDER BY h.created_at DESC
            ''', (task_id,))
            return [dict(row) for row in cursor.fetchall()]


class DeveloperDAO:
    """开发人员数据访问对象"""

    @staticmethod
    def create(name: str, email: str, git_name: str = None,
               role: str = 'developer', project_id: int = None) -> int:
        """创开发人员"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pm_developers (name, email, git_name, role, project_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (name, email, git_name, role, project_id))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(developer_id: int) -> Optional[Dict]:
        """根据ID获取开发人员"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT d.*, p.name as project_name
                FROM pm_developers d
                LEFT JOIN pm_projects p ON d.project_id = p.id
                WHERE d.id = ?
            ''', (developer_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_email(email: str) -> Optional[Dict]:
        """根据邮箱获取开发人员"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT d.*, p.name as project_name
                FROM pm_developers d
                LEFT JOIN pm_projects p ON d.project_id = p.id
                WHERE d.email = ?
            ''', (email,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_project(project_id: int) -> List[Dict]:
        """获取项目的所有开发人员"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT d.*, p.name as project_name
                FROM pm_developers d
                LEFT JOIN pm_projects p ON d.project_id = p.id
                WHERE d.project_id = ? AND d.is_active = 1
                ORDER BY d.name
            ''', (project_id,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_all() -> List[Dict]:
        """获取所有开发人员"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT d.*, p.name as project_name
                FROM pm_developers d
                LEFT JOIN pm_projects p ON d.project_id = p.id
                WHERE d.is_active = 1
                ORDER BY d.name
            ''')
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def update(developer_id: int, **kwargs) -> bool:
        """更新开发人员信息"""
        allowed_fields = ['name', 'email', 'git_name', 'role', 'project_id', 'avatar_url']
        updates = []
        params = []

        for key, value in kwargs.items():
            if key in allowed_fields and value is not None:
                updates.append(f"{key} = ?")
                params.append(value)

        if not updates:
            return False

        params.append(developer_id)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE pm_developers SET {', '.join(updates)} WHERE id = ?
            ''', params)
            conn.commit()
            return cursor.rowcount > 0


class MessageDAO:
    """消息数据访问对象"""

    @staticmethod
    def create(msg_type: str, title: str, content: str = None,
               sender_id: int = None, receiver_id: int = None,
               related_task_id: int = None) -> int:
        """创建消息"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pm_messages
                (msg_type, title, content, sender_id, receiver_id, related_task_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (msg_type, title, content, sender_id, receiver_id, related_task_id))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_receiver(receiver_id: int, unread_only: bool = False) -> List[Dict]:
        """获取接收者的消息"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT m.*, s.name as sender_name,
                       t.title as task_title
                FROM pm_messages m
                LEFT JOIN pm_developers s ON m.sender_id = s.id
                LEFT JOIN pm_tasks t ON m.related_task_id = t.id
                WHERE m.receiver_id = ?
            '''
            if unread_only:
                query += ' AND m.is_read = 0'
            query += ' ORDER BY m.created_at DESC'

            cursor.execute(query, (receiver_id,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_unread_count(receiver_id: int) -> int:
        """获取未读消息数量"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) as count FROM pm_messages
                WHERE receiver_id = ? AND is_read = 0
            ''', (receiver_id,))
            row = cursor.fetchone()
            return row['count'] if row else 0

    @staticmethod
    def mark_as_read(message_id: int) -> bool:
        """标记消息为已读"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE pm_messages SET is_read = 1 WHERE id = ?', (message_id,))
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def mark_all_as_read(receiver_id: int) -> bool:
        """标记所有消息为已读"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE pm_messages SET is_read = 1 WHERE receiver_id = ?', (receiver_id,))
            conn.commit()
            return cursor.rowcount > 0


class BugDAO:
    """Bug记录数据访问对象"""

    @staticmethod
    def create(title: str, description: str = None, severity: str = '中',
               task_id: int = None, reporter_id: int = None,
               assignee_id: int = None, git_commit_hash: str = None) -> int:
        """创建Bug记录"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pm_bugs
                (title, description, severity, task_id, reporter_id,
                 assignee_id, git_commit_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (title, description, severity, task_id, reporter_id,
                  assignee_id, git_commit_hash))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_assignee(assignee_id: int) -> List[Dict]:
        """获取分配给某人的Bug"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT b.*, t.title as task_title,
                       r.name as reporter_name
                FROM pm_bugs b
                LEFT JOIN pm_tasks t ON b.task_id = t.id
                LEFT JOIN pm_developers r ON b.reporter_id = r.id
                WHERE b.assignee_id = ? AND b.status != '已解决'
                ORDER BY
                    CASE b.severity WHEN '紧急' THEN 1 WHEN '高' THEN 2 WHEN '中' THEN 3 ELSE 4 END,
                    b.created_at DESC
            ''', (assignee_id,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_open_bugs(project_id: int = None) -> List[Dict]:
        """获取未解决的Bug列表"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = '''
                SELECT b.*, t.title as task_title, p.name as project_name,
                       a.name as assignee_name, r.name as reporter_name
                FROM pm_bugs b
                LEFT JOIN pm_tasks t ON b.task_id = t.id
                LEFT JOIN pm_projects p ON t.project_id = p.id
                LEFT JOIN pm_developers a ON b.assignee_id = a.id
                LEFT JOIN pm_developers r ON b.reporter_id = r.id
                WHERE b.status != '已解决'
            '''
            params = []
            if project_id:
                query += ' AND t.project_id = ?'
                params.append(project_id)
            query += ' ORDER BY b.severity, b.created_at DESC'

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def update(bug_id: int, **kwargs) -> bool:
        """更新Bug状态"""
        allowed_fields = ['title', 'description', 'severity', 'status',
                         'assignee_id', 'fix_suggestion']
        updates = []
        params = []

        for key, value in kwargs.items():
            if key in allowed_fields and value is not None:
                updates.append(f"{key} = ?")
                params.append(value)

        if 'status' in kwargs and kwargs['status'] == '已解决':
            updates.append("resolved_at = CURRENT_TIMESTAMP")

        if not updates:
            return False

        params.append(bug_id)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE pm_bugs SET {', '.join(updates)} WHERE id = ?
            ''', params)
            conn.commit()
            return cursor.rowcount > 0


class ProjectDAO:
    """项目数据访问对象"""

    @staticmethod
    def create(name: str, description: str = None,
               repo_path: str = None, git_project_id: int = None) -> int:
        """创建项目"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pm_projects (name, description, repo_path, git_project_id)
                VALUES (?, ?, ?, ?)
            ''', (name, description, repo_path, git_project_id))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(project_id: int) -> Optional[Dict]:
        """根据ID获取项目"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM pm_projects WHERE id = ?', (project_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_all() -> List[Dict]:
        """获取所有项目"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM pm_projects ORDER BY name')
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_with_stats(project_id: int) -> Optional[Dict]:
        """获取项目及其统计信息"""
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 获取项目基本信息
            cursor.execute('SELECT * FROM pm_projects WHERE id = ?', (project_id,))
            project = cursor.fetchone()
            if not project:
                return None

            # 统计任务
            cursor.execute('''
                SELECT status, COUNT(*) as count
                FROM pm_tasks WHERE project_id = ?
                GROUP BY status
            ''', (project_id,))
            status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

            # 统计开发人员
            cursor.execute('''
                SELECT COUNT(*) as count FROM pm_developers
                WHERE project_id = ? AND is_active = 1
            ''', (project_id,))
            dev_count = cursor.fetchone()['count']

            result = dict(project)
            result['status_counts'] = status_counts
            result['developer_count'] = dev_count

            # 计算完成率
            total = sum(status_counts.values())
            completed = status_counts.get('已完成', 0)
            result['completion_rate'] = round(completed / total * 100, 1) if total > 0 else 0

            return result


# ========== 业务逻辑层 (Service) ==========

class TaskService:
    """任务业务逻辑服务"""

    @staticmethod
    def create_task(project_id: int, title: str, description: str = None,
                    status: str = '待认领', priority: str = '中',
                    assignee_id: int = None, reporter_id: int = None,
                    due_date: str = None, depends_on: int = None,
                    module: str = None) -> Dict:
        """创建任务并记录历史"""
        task_id = TaskDAO.create(
            project_id=project_id,
            title=title,
            description=description,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            reporter_id=reporter_id,
            due_date=due_date,
            depends_on=depends_on,
            module=module
        )

        # 记录创建历史
        TaskHistoryDAO.add(
            task_id=task_id,
            field_name='created',
            old_value='',
            new_value=title,
            changed_by=reporter_id,
            reason='任务创建'
        )

        # 如果有依赖，检测是否被阻塞
        if depends_on:
            TaskService._check_and_update_blocked_status(task_id)

        return TaskDAO.get_by_id(task_id)

    @staticmethod
    def update_task(task_id: int, changed_by: int = None, **kwargs) -> Dict:
        """更新任务并记录历史"""
        old_task = TaskDAO.get_by_id(task_id)
        if not old_task:
            raise ValueError(f"Task {task_id} not found")

        # 记录每个字段的变更
        for field, new_value in kwargs.items():
            old_value = old_task.get(field)
            if old_value != new_value:
                TaskHistoryDAO.add(
                    task_id=task_id,
                    field_name=field,
                    old_value=str(old_value) if old_value else '',
                    new_value=str(new_value) if new_value else '',
                    changed_by=changed_by,
                    reason=kwargs.get('reason')
                )

        # 更新任务
        TaskDAO.update(task_id, **kwargs)

        # 检测阻塞状态变化
        if 'status' in kwargs:
            TaskService._check_and_update_blocked_status(task_id)

        return TaskDAO.get_by_id(task_id)

    @staticmethod
    def _check_and_update_blocked_status(task_id: int):
        """检查并更新任务的阻塞状态"""
        task = TaskDAO.get_by_id(task_id)
        if not task or not task.get('depends_on'):
            return

        # 获取前置任务
        depends_on_id = task['depends_on']
        depends_on = TaskDAO.get_by_id(depends_on_id)

        if not depends_on:
            return

        # 如果前置任务未完成，且当前任务不是"已完成"，则标记为被阻塞
        if depends_on['status'] not in ['已完成', '待联调', '测试中'] and task['status'] != '已完成':
            if task['status'] != '被阻塞':
                TaskDAO.update(task_id, status='被阻塞')
        else:
            # 前置任务已完成，取消阻塞状态
            if task['status'] == '被阻塞':
                # 恢复到开发中
                TaskDAO.update(task_id, status='开发中')

    @staticmethod
    def get_my_tasks(assignee_id: int, project_id: int = None) -> Dict:
        """获取我的任务概览"""
        all_tasks = TaskDAO.get_by_assignee(assignee_id, project_id=project_id)

        # 分类统计
        stats = {
            'total': len(all_tasks),
            'pending': 0,
            'in_progress': 0,
            'blocked': 0,
            'completed': 0
        }

        for task in all_tasks:
            status = task.get('status', '待认领')
            if status == '待认领':
                stats['pending'] += 1
            elif status == '开发中':
                stats['in_progress'] += 1
            elif status == '被阻塞':
                stats['blocked'] += 1
            elif status == '已完成':
                stats['completed'] += 1

        # 获取阻塞我的任务
        blockers = TaskService.get_blocking_tasks(assignee_id)

        return {
            'tasks': all_tasks,
            'stats': stats,
            'blockers': blockers
        }

    @staticmethod
    def get_blocking_tasks(assignee_id: int, project_id: int = None) -> List[Dict]:
        """获取阻塞我工作的前置任务"""
        return TaskDAO.get_my_blockers(assignee_id, project_id=project_id)

    @staticmethod
    def send_reminder(task_id: int, sender_id: int) -> int:
        """发送催促消息"""
        task = TaskDAO.get_by_id(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        depends_on_id = task.get('depends_on')
        if not depends_on_id:
            raise ValueError("该任务没有前置依赖")

        depends_on = TaskDAO.get_by_id(depends_on_id)
        if not depends_on or not depends_on.get('assignee_id'):
            raise ValueError("无法找到阻塞者")

        blocker_id = depends_on['assignee_id']
        if blocker_id == sender_id:
            raise ValueError("不能催促自己")

        # 创建催促消息
        message = MessageDAO.create(
            msg_type='reminder',
            title=f'【催促】任务阻塞提醒',
            content=f'您在任务「{task["title"]}」中的工作被「{depends_on["title"]}」阻塞。\n'
                    f'请尽快完成前置任务，以便对方能够继续工作。',
            sender_id=sender_id,
            receiver_id=blocker_id,
            related_task_id=depends_on_id
        )

        return message


class ChatService:
    """AI对话服务"""

    @staticmethod
    def parse_task_creation(message: str) -> Optional[Dict]:
        """从用户消息中解析任务创建意图"""
        # 简单的关键词匹配，实际可以用LLM来解析
        keywords = {
            'title': ['添加任务', '创建任务', '新任务', '任务：', '任务:'],
            'project': ['platform', 'agent', '项目'],
            'assignee': ['负责人是', ' assignee ', ' 负责人 '],
            'due_date': ['截止', 'due', 'deadline', '下周五', '下周', '明天', '后天']
        }

        result = {}

        # 简化处理，实际应该用LLM来解析
        if '添加任务' in message or '创建任务' in message or '新任务' in message:
            result['action'] = 'create_task'

            # 提取标题（简单取冒号后面的内容）
            for kw in keywords['title']:
                if kw in message:
                    idx = message.index(kw) + len(kw)
                    result['title'] = message[idx:].strip().split('\n')[0]
                    break

        return result if 'action' in result else None

    @staticmethod
    def save_chat(developer_id: int, project_id: int, role: str, content: str, session_id: str = None):
        """保存对话历史"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pm_chat_history (developer_id, project_id, role, content, session_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (developer_id, project_id, role, content, session_id))
            conn.commit()


# ========== 初始化数据库 ==========

def init_task_db():
    """初始化任务管理相关的数据库表"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # ========== 1. 项目表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                repo_path TEXT,
                git_project_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ========== 2. 开发人员表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_developers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                git_name TEXT,
                role TEXT DEFAULT 'developer',
                project_id INTEGER,
                avatar_url TEXT,
                is_active INTEGER DEFAULT 1,
                last_active TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES pm_projects(id)
            )
        ''')

        # ========== 3. 任务表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT '待认领',
                priority TEXT DEFAULT '中',
                module TEXT,
                assignee_id INTEGER,
                reporter_id INTEGER,
                due_date DATE,
                depends_on INTEGER,
                blocked_by_id INTEGER,
                git_commit_hash TEXT,
                progress INTEGER DEFAULT 0,
                tags TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES pm_projects(id),
                FOREIGN KEY (assignee_id) REFERENCES pm_developers(id),
                FOREIGN KEY (reporter_id) REFERENCES pm_developers(id),
                FOREIGN KEY (depends_on) REFERENCES pm_tasks(id)
            )
        ''')

        # ========== 4. 任务历史记录表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                changed_by INTEGER,
                change_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES pm_tasks(id),
                FOREIGN KEY (changed_by) REFERENCES pm_developers(id)
            )
        ''')

        # ========== 5. 消息/通知表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                sender_id INTEGER,
                receiver_id INTEGER,
                related_task_id INTEGER,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES pm_developers(id),
                FOREIGN KEY (receiver_id) REFERENCES pm_developers(id),
                FOREIGN KEY (related_task_id) REFERENCES pm_tasks(id)
            )
        ''')

        # ========== 6. Bug记录表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_bugs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                title TEXT NOT NULL,
                description TEXT,
                severity TEXT DEFAULT '中',
                status TEXT DEFAULT '待处理',
                reporter_id INTEGER,
                assignee_id INTEGER,
                fix_suggestion TEXT,
                git_commit_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES pm_tasks(id),
                FOREIGN KEY (reporter_id) REFERENCES pm_developers(id),
                FOREIGN KEY (assignee_id) REFERENCES pm_developers(id)
            )
        ''')

        # ========== 7. AI对话记录表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                developer_id INTEGER,
                project_id INTEGER,
                role TEXT,
                content TEXT,
                session_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (developer_id) REFERENCES pm_developers(id),
                FOREIGN KEY (project_id) REFERENCES pm_projects(id)
            )
        ''')

        # 添加session_id列（如果不存在）
        try:
            cursor.execute("ALTER TABLE pm_chat_history ADD COLUMN session_id TEXT")
        except:
            pass  # 列可能已存在

        # ========== 8. 智能体执行日志表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_agent_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_type TEXT NOT NULL,
                task_id INTEGER,
                action TEXT,
                result TEXT,
                executed_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES pm_tasks(id)
            )
        ''')

        # ========== 9. 代码生成锁表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_code_locks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                session_id TEXT NOT NULL,
                developer_id INTEGER,
                status TEXT DEFAULT 'locked',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES pm_projects(id)
            )
        ''')

        # ========== 10. Agent任务认领表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_agent_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                description TEXT,
                project_id INTEGER,
                developer_id INTEGER,
                session_id TEXT,
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                result TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES pm_projects(id),
                FOREIGN KEY (developer_id) REFERENCES pm_developers(id)
            )
        ''')

        # ========== 11. 多Tab会话表 ==========
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                developer_id INTEGER,
                project_id INTEGER,
                view_type TEXT DEFAULT 'dashboard',
                context TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP,
                FOREIGN KEY (developer_id) REFERENCES pm_developers(id),
                FOREIGN KEY (project_id) REFERENCES pm_projects(id)
            )
        ''')

        # 创建索引以提高查询性能
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_code_locks_session ON pm_code_locks(session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_code_locks_file ON pm_code_locks(file_path, project_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON pm_agent_tasks(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_agent_tasks_session ON pm_agent_tasks(session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_session ON pm_sessions(session_id)')

        conn.commit()
        print("Task management database initialized")


if __name__ == '__main__':
    init_task_db()