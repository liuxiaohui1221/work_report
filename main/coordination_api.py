#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
协调服务 API - 多Tab会话管理、任务锁、Agent协调
"""

import json
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify
from main.coordination import (
    SessionManager, CodeLockManager, AgentTaskCoordinator,
    get_code_generator
)
from main.models import get_db_connection


# 创建蓝图
coord_bp = Blueprint('coord', __name__, url_prefix='/api/coord')


# ========== 会话管理 API ==========

@coord_bp.route('/session/create', methods=['POST'])
def create_session():
    """创建新Tab会话"""
    data = request.json
    developer_id = data.get('developer_id')
    project_id = data.get('project_id')
    view_type = data.get('view_type', 'dashboard')

    session_id = SessionManager.create_session(developer_id, project_id, view_type)

    return jsonify({
        'success': True,
        'session_id': session_id
    })


@coord_bp.route('/session/<session_id>', methods=['GET'])
def get_session(session_id):
    """获取会话信息"""
    session = SessionManager.get_session(session_id)
    if not session:
        return jsonify({'error': '会话不存在'}), 404

    # 获取会话的任务
    tasks = AgentTaskCoordinator.get_session_tasks(session_id)
    locks = CodeLockManager.get_session_locks(session_id)

    return jsonify({
        'session': session,
        'tasks': tasks,
        'locks': locks
    })


@coord_bp.route('/session/<session_id>', methods=['PUT'])
def update_session(session_id):
    """更新会话信息"""
    data = request.json

    SessionManager.update_session(session_id, **data)

    return jsonify({'success': True})


@coord_bp.route('/sessions/<int:developer_id>', methods=['GET'])
def get_developer_sessions(developer_id):
    """获取开发者的所有活跃会话"""
    sessions = SessionManager.get_developer_sessions(developer_id)

    # 获取每个会话的任务和锁信息
    for session in sessions:
        session['tasks'] = AgentTaskCoordinator.get_session_tasks(session['session_id'])
        session['locks'] = CodeLockManager.get_session_locks(session['session_id'])

    return jsonify({
        'sessions': sessions,
        'count': len(sessions)
    })


@coord_bp.route('/session/<session_id>/close', methods=['POST'])
def close_session(session_id):
    """关闭会话，释放所有锁和取消任务"""
    # 释放所有锁
    CodeLockManager.release_session_locks(session_id)

    # 取消所有待处理任务
    AgentTaskCoordinator.cancel_session_tasks(session_id)

    return jsonify({'success': True})


# ========== 代码锁 API ==========

@coord_bp.route('/lock/acquire', methods=['POST'])
def acquire_lock():
    """
    尝试获取文件锁
    请求体：
    {
        "project_id": 1,
        "file_path": "src/utils/helper.js",
        "session_id": "uuid",
        "developer_id": 1,
        "ttl_minutes": 30
    }
    """
    data = request.json
    project_id = data.get('project_id')
    file_path = data.get('file_path')
    session_id = data.get('session_id')
    developer_id = data.get('developer_id')
    ttl = data.get('ttl_minutes', 30)

    success, lock_info = CodeLockManager.acquire_lock(
        project_id, file_path, session_id, developer_id, ttl
    )

    return jsonify({
        'success': success,
        'lock': lock_info if success else None,
        'message': '锁定成功' if success else '文件已被其他会话锁定'
    })


@coord_bp.route('/lock/release', methods=['POST'])
def release_lock():
    """释放文件锁"""
    data = request.json
    project_id = data.get('project_id')
    file_path = data.get('file_path')
    session_id = data.get('session_id')

    success = CodeLockManager.release_lock(project_id, file_path, session_id)

    return jsonify({
        'success': success,
        'message': '锁已释放' if success else '释放失败'
    })


@coord_bp.route('/locks/<int:project_id>', methods=['GET'])
def get_project_locks(project_id):
    """获取项目的所有活跃锁"""
    locks = CodeLockManager.get_file_locks(project_id)
    return jsonify({
        'locks': locks,
        'count': len(locks)
    })


# ========== Agent任务协调 API ==========

@coord_bp.route('/task/claim', methods=['POST'])
def claim_task():
    """
    Agent认领任务
    请求体：
    {
        "task_type": "code_generation",
        "developer_id": 1,
        "project_id": 1,
        "session_id": "uuid",
        "description": "..."
    }
    """
    data = request.json
    task_type = data.get('task_type')
    developer_id = data.get('developer_id')
    project_id = data.get('project_id')
    session_id = data.get('session_id')
    description = data.get('description')

    task = AgentTaskCoordinator.claim_task(
        task_type, developer_id, project_id, session_id, description
    )

    if task:
        return jsonify({
            'success': True,
            'task': task
        })
    else:
        return jsonify({
            'success': False,
            'message': '没有可认领的任务'
        })


@coord_bp.route('/task/create', methods=['POST'])
def create_task():
    """创建Agent任务"""
    data = request.json

    task_id = AgentTaskCoordinator.create_task(
        task_type=data.get('task_type'),
        description=data.get('description'),
        project_id=data.get('project_id'),
        developer_id=data.get('developer_id'),
        session_id=data.get('session_id'),
        priority=data.get('priority', 0)
    )

    return jsonify({
        'success': True,
        'task_id': task_id
    })


@coord_bp.route('/task/<int:task_id>/complete', methods=['POST'])
def complete_task(task_id):
    """完成任务"""
    data = request.json
    result = data.get('result')
    error = data.get('error')

    success = AgentTaskCoordinator.complete_task(task_id, result, error)

    return jsonify({
        'success': success
    })


@coord_bp.route('/task/<int:task_id>/fail', methods=['POST'])
def fail_task(task_id):
    """标记任务失败"""
    data = request.json
    error = data.get('error')

    success = AgentTaskCoordinator.fail_task(task_id, error)

    return jsonify({
        'success': success
    })


@coord_bp.route('/tasks/active', methods=['GET'])
def get_active_tasks():
    """获取进行中的任务"""
    project_id = request.args.get('project_id', type=int)
    task_type = request.args.get('type')

    tasks = AgentTaskCoordinator.get_active_tasks(project_id, task_type)

    return jsonify({
        'tasks': tasks,
        'count': len(tasks)
    })


@coord_bp.route('/tasks/session/<session_id>', methods=['GET'])
def get_session_tasks(session_id):
    """获取会话的所有任务"""
    tasks = AgentTaskCoordinator.get_session_tasks(session_id)
    return jsonify({
        'tasks': tasks,
        'count': len(tasks)
    })


# ========== 异步代码生成 API ==========

@coord_bp.route('/code/generate/async', methods=['POST'])
def start_async_code_generation():
    """
    启动异步代码生成
    请求体：
    {
        "session_id": "uuid",
        "task_id": 1,
        "project_id": 1,
        "requirement": "..."
    }
    """
    data = request.json
    session_id = data.get('session_id')
    task_id = data.get('task_id')
    project_id = data.get('project_id')
    requirement = data.get('requirement')

    generator = get_code_generator()
    success = generator.start_generation(session_id, task_id, project_id, requirement)

    return jsonify({
        'success': success,
        'message': '生成已启动' if success else '已有生成任务在进行'
    })


@coord_bp.route('/code/generate/status/<session_id>', methods=['GET'])
def get_generation_status(session_id):
    """获取异步生成状态"""
    generator = get_code_generator()
    result = generator.get_result(session_id)

    if result:
        return jsonify(result)
    else:
        return jsonify({
            'status': 'not_found',
            'message': '未找到生成任务'
        })


@coord_bp.route('/code/generate/cancel/<session_id>', methods=['POST'])
def cancel_generation(session_id):
    """取消代码生成"""
    generator = get_code_generator()
    success = generator.cancel_generation(session_id)

    return jsonify({
        'success': success
    })


# ========== 实时状态 API ==========

@coord_bp.route('/status/<int:developer_id>', methods=['GET'])
def get_developer_status(developer_id):
    """获取开发者的实时状态"""
    # 获取所有活跃会话
    sessions = SessionManager.get_developer_sessions(developer_id)

    # 收集所有信息
    active_tasks = []
    active_locks = []

    for session in sessions:
        tasks = AgentTaskCoordinator.get_session_tasks(session['session_id'])
        active_tasks.extend([t for t in tasks if t['status'] in ['pending', 'in_progress']])

        locks = CodeLockManager.get_session_locks(session['session_id'])
        active_locks.extend(locks)

    # 获取未读消息
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as count FROM pm_messages
            WHERE receiver_id = ? AND is_read = 0
        ''', (developer_id,))
        unread = cursor.fetchone()['count']

    return jsonify({
        'developer_id': developer_id,
        'session_count': len(sessions),
        'active_tasks': len(active_tasks),
        'active_locks': len(active_locks),
        'unread_messages': unread,
        'sessions': [{
            'session_id': s['session_id'],
            'view_type': s['view_type'],
            'project_id': s['project_id'],
            'last_activity': s['last_activity']
        } for s in sessions]
    })


# ========== 导出主要类 ==========

def init_coordination():
    """初始化协调服务"""
    # 清理过期数据
    SessionManager.cleanup_old_sessions()
    CodeLockManager.cleanup_expired_locks()
    print("[Coordination] Initialized")


if __name__ == '__main__':
    init_coordination()