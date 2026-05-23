#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能体协调服务 - 多Tab会话管理、任务锁、Agent协调
支持多个Tab页并行操作，Agent间共享任务避免冲突
"""

import os
import json
import uuid
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from main.models import get_db_connection, DeveloperDAO, ProjectDAO


class SessionManager:
    """多Tab会话管理器"""

    @staticmethod
    def create_session(developer_id: int, project_id: int = None,
                       view_type: str = 'dashboard') -> str:
        """为新Tab创建会话"""
        session_id = str(uuid.uuid4())

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pm_sessions (session_id, developer_id, project_id, view_type, last_activity)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (session_id, developer_id, project_id, view_type))
            conn.commit()

        return session_id

    @staticmethod
    def get_session(session_id: str) -> Optional[Dict]:
        """获取会话信息"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM pm_sessions WHERE session_id = ?', (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def update_session(session_id: str, **kwargs):
        """更新会话信息"""
        updates = []
        params = []

        for key, value in kwargs.items():
            if key in ['view_type', 'context', 'project_id']:
                updates.append(f"{key} = ?")
                params.append(value)

        if updates:
            updates.append('last_activity = CURRENT_TIMESTAMP')
            params.append(session_id)

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f'''
                    UPDATE pm_sessions SET {', '.join(updates)} WHERE session_id = ?
                ''', params)
                conn.commit()

    @staticmethod
    def get_developer_sessions(developer_id: int) -> List[Dict]:
        """获取开发者的所有活跃会话"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM pm_sessions
                WHERE developer_id = ?
                ORDER BY last_activity DESC
            ''', (developer_id,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def cleanup_old_sessions(max_age_minutes: int = 60):
        """清理过期的会话"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM pm_sessions
                WHERE datetime(last_activity) < datetime('now', '-' || ? || ' minutes')
            ''', (max_age_minutes,))
            conn.commit()
            return cursor.rowcount


class CodeLockManager:
    """代码生成锁管理器 - 防止多Agent同时修改同一文件"""

    @staticmethod
    def acquire_lock(project_id: int, file_path: str, session_id: str,
                     developer_id: int = None, ttl_minutes: int = 30) -> Tuple[bool, Dict]:
        """
        尝试获取文件锁
        返回: (成功标志, 锁信息)
        """
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 检查是否已有锁
            cursor.execute('''
                SELECT * FROM pm_code_locks
                WHERE project_id = ? AND file_path = ? AND status = 'locked'
                AND datetime(expires_at) > datetime('now')
            ''', (project_id, file_path))

            existing = cursor.fetchone()

            if existing:
                # 锁已存在，检查是否是自己创建的
                if existing['session_id'] == session_id:
                    # 续期自己的锁
                    expires = (datetime.now() + timedelta(minutes=ttl_minutes)).strftime('%Y-%m-%d %H:%M:%S')
                    cursor.execute('''
                        UPDATE pm_code_locks SET expires_at = ? WHERE id = ?
                    ''', (expires, existing['id']))
                    conn.commit()
                    return True, dict(existing)
                else:
                    # 被其他会话锁定
                    return False, dict(existing)

            # 创建新锁
            expires = (datetime.now() + timedelta(minutes=ttl_minutes)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('''
                INSERT INTO pm_code_locks
                (project_id, file_path, session_id, developer_id, status, expires_at)
                VALUES (?, ?, ?, ?, 'locked', ?)
            ''', (project_id, file_path, session_id, developer_id, expires))
            conn.commit()

            return True, {'id': cursor.lastrowid, 'session_id': session_id}

    @staticmethod
    def release_lock(project_id: int, file_path: str, session_id: str) -> bool:
        """释放文件锁"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE pm_code_locks
                SET status = 'released'
                WHERE project_id = ? AND file_path = ? AND session_id = ?
            ''', (project_id, file_path, session_id))
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def release_session_locks(session_id: str) -> int:
        """释放会话的所有锁"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE pm_code_locks
                SET status = 'released'
                WHERE session_id = ?
            ''', (session_id,))
            conn.commit()
            return cursor.rowcount

    @staticmethod
    def get_session_locks(session_id: str) -> List[Dict]:
        """获取会话的所有锁"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM pm_code_locks
                WHERE session_id = ? AND status = 'locked'
            ''', (session_id,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_file_locks(project_id: int) -> List[Dict]:
        """获取项目的所有活跃锁"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM pm_code_locks
                WHERE project_id = ? AND status = 'locked'
                AND datetime(expires_at) > datetime('now')
                ORDER BY created_at DESC
            ''', (project_id,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def cleanup_expired_locks():
        """清理过期的锁"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE pm_code_locks
                SET status = 'expired'
                WHERE status = 'locked' AND datetime(expires_at) < datetime('now')
            ''')
            conn.commit()
            return cursor.rowcount


class AgentTaskCoordinator:
    """Agent任务协调器 - 多Agent并行时任务分配和状态同步"""

    @staticmethod
    def claim_task(task_type: str, developer_id: int = None,
                   project_id: int = None, session_id: str = None,
                   description: str = None) -> Optional[Dict]:
        """
        认领一个任务（避免多个Agent做同一件事）
        返回: 任务信息或None（无任务可认领）
        """
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 查找等待中的同类任务
            cursor.execute('''
                SELECT * FROM pm_agent_tasks
                WHERE task_type = ? AND status = 'pending'
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            ''', (task_type,))

            task = cursor.fetchone()

            if not task:
                # 创建新任务
                task_id = AgentTaskCoordinator.create_task(
                    task_type, description, project_id,
                    developer_id, session_id
                )
                if task_id:
                    cursor.execute('SELECT * FROM pm_agent_tasks WHERE id = ?', (task_id,))
                    task = cursor.fetchone()

            if task:
                # 标记为进行中
                cursor.execute('''
                    UPDATE pm_agent_tasks
                    SET status = 'in_progress',
                        developer_id = ?, session_id = ?,
                        started_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (developer_id, session_id, task['id']))
                conn.commit()
                return dict(task)

            return None

    @staticmethod
    def create_task(task_type: str, description: str = None,
                    project_id: int = None, developer_id: int = None,
                    session_id: str = None, priority: int = 0) -> int:
        """创建新任务"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pm_agent_tasks
                (task_type, description, project_id, developer_id, session_id, priority)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (task_type, description, project_id, developer_id, session_id, priority))
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def complete_task(task_id: int, result: str = None, error: str = None) -> bool:
        """完成任务"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE pm_agent_tasks
                SET status = 'completed', result = ?, error = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (result, error, task_id))
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def fail_task(task_id: int, error: str) -> bool:
        """标记任务失败"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE pm_agent_tasks
                SET status = 'failed', error = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (error, task_id))
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def get_task(task_id: int) -> Optional[Dict]:
        """获取任务信息"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM pm_agent_tasks WHERE id = ?', (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_session_tasks(session_id: str) -> List[Dict]:
        """获取会话的所有任务"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM pm_agent_tasks
                WHERE session_id = ?
                ORDER BY created_at DESC
            ''', (session_id,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_active_tasks(project_id: int = None, task_type: str = None) -> List[Dict]:
        """获取进行中的任务"""
        with get_db_connection() as conn:
            cursor = conn.cursor()

            query = 'SELECT * FROM pm_agent_tasks WHERE status IN ("pending", "in_progress")'
            params = []

            if project_id:
                query += ' AND project_id = ?'
                params.append(project_id)

            if task_type:
                query += ' AND task_type = ?'
                params.append(task_type)

            query += ' ORDER BY priority DESC, created_at ASC'

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def cancel_session_tasks(session_id: str) -> int:
        """取消会话的所有待处理任务"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE pm_agent_tasks
                SET status = 'cancelled'
                WHERE session_id = ? AND status IN ('pending', 'in_progress')
            ''', (session_id,))
            conn.commit()
            return cursor.rowcount


class AsyncCodeGenerator:
    """异步代码生成器 - 支持多任务并行"""

    def __init__(self):
        self.generators = {}  # session_id -> generator_thread
        self.results = {}  # session_id -> result
        self.lock = threading.Lock()

    def start_generation(self, session_id: str, task_id: int,
                         project_id: int, requirement: str) -> bool:
        """启动异步代码生成"""
        with self.lock:
            if session_id in self.generators:
                return False  # 已有生成器在运行

            # 创建生成线程
            thread = threading.Thread(
                target=self._generate_code,
                args=(session_id, task_id, project_id, requirement),
                daemon=True
            )
            self.generators[session_id] = thread
            self.results[session_id] = {'status': 'running', 'progress': 0}
            thread.start()
            return True

    def _generate_code(self, session_id: str, task_id: int,
                       project_id: int, requirement: str):
        """后台生成代码"""
        try:
            # 获取项目信息
            project = ProjectDAO.get_by_id(project_id)
            if not project:
                self._set_result(session_id, 'error', '项目不存在')
                return

            repo_path = project.get('repo_path')
            if not repo_path:
                self._set_result(session_id, 'error', '项目未配置Git路径')
                return

            # 调用LLM生成代码
            from main.ai_chat import generate_code_for_task
            result = generate_code_for_task(requirement, project_id)

            if 'error' in result:
                self._set_result(session_id, 'error', result['error'])
                AgentTaskCoordinator.fail_task(task_id, result['error'])
            else:
                files = result.get('files', [])

                # 检查文件锁
                locked_files = []
                for f in files:
                    success, lock_info = CodeLockManager.acquire_lock(
                        project_id, f['path'], session_id,
                        ttl_minutes=60
                    )
                    if not success:
                        locked_files.append(f['path'])

                if locked_files:
                    self._set_result(session_id, 'warning',
                        f'部分文件被锁定: {", ".join(locked_files)}')
                    # 仍然可以生成，只是不能修改被锁的文件
                    AgentTaskCoordinator.complete_task(task_id, json.dumps(result, ensure_ascii=False))
                else:
                    # 保存待审核代码
                    from main.ai_chat import save_pending_code
                    developer_id = self._get_session_developer(session_id)
                    code_id = save_pending_code(developer_id, project_id, files, requirement)

                    self._set_result(session_id, 'success', {
                        'code_id': code_id,
                        'files': files,
                        'summary': result.get('summary', '')
                    })
                    AgentTaskCoordinator.complete_task(task_id, json.dumps(result, ensure_ascii=False))

        except Exception as e:
            self._set_result(session_id, 'error', str(e))
            AgentTaskCoordinator.fail_task(task_id, str(e))

        finally:
            # 清理
            with self.lock:
                self.generators.pop(session_id, None)

    def _set_result(self, session_id: str, status: str, data):
        """设置结果"""
        with self.lock:
            self.results[session_id] = {'status': status, 'data': data, 'time': datetime.now().isoformat()}

    def _get_session_developer(self, session_id: str) -> int:
        """获取会话对应的开发者"""
        session = SessionManager.get_session(session_id)
        return session.get('developer_id') if session else None

    def get_result(self, session_id: str) -> Optional[Dict]:
        """获取生成结果"""
        with self.lock:
            return self.results.get(session_id)

    def cancel_generation(self, session_id: str) -> bool:
        """取消生成"""
        with self.lock:
            if session_id in self.generators:
                # 不能直接终止线程，但可以标记为取消
                self._set_result(session_id, 'cancelled', '用户取消')
                return True
        return False

    def get_progress(self, session_id: str) -> int:
        """获取进度"""
        with self.lock:
            result = self.results.get(session_id, {})
            return result.get('progress', 0)


# 全局实例
_code_generator = None
_code_generator_lock = threading.Lock()


def get_code_generator() -> AsyncCodeGenerator:
    """获取异步代码生成器实例"""
    global _code_generator
    if _code_generator is None:
        with _code_generator_lock:
            if _code_generator is None:
                _code_generator = AsyncCodeGenerator()
    return _code_generator


# ========== 导出 ==========

__all__ = [
    'SessionManager',
    'CodeLockManager',
    'AgentTaskCoordinator',
    'AsyncCodeGenerator',
    'get_code_generator'
]