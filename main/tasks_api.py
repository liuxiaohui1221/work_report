#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务管理 API - 任务CRUD、依赖管理、历史追踪
"""

import json
from datetime import datetime
from flask import Blueprint, request, jsonify
from main.models import (
    TaskDAO, TaskHistoryDAO, DeveloperDAO, MessageDAO,
    ProjectDAO, BugDAO, TaskService, init_task_db
)


# 创建蓝图
tasks_bp = Blueprint('tasks', __name__, url_prefix='/api/tasks')


# ========== 项目管理 API ==========

@tasks_bp.route('/projects', methods=['GET'])
def get_projects():
    """获取项目列表"""
    projects = ProjectDAO.get_all()
    return jsonify(projects)


@tasks_bp.route('/projects', methods=['POST'])
def create_project():
    """创建项目"""
    data = request.json
    try:
        project_id = ProjectDAO.create(
            name=data.get('name'),
            description=data.get('description'),
            repo_path=data.get('repo_path'),
            git_project_id=data.get('git_project_id')
        )
        return jsonify({'id': project_id, 'name': data.get('name')}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@tasks_bp.route('/projects/<int:project_id>', methods=['GET'])
def get_project(project_id):
    """获取项目详情（含统计）"""
    project = ProjectDAO.get_with_stats(project_id)
    if not project:
        return jsonify({'error': '项目不存在'}), 404
    return jsonify(project)


@tasks_bp.route('/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    """删除项目"""
    with TaskDAO.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM pm_tasks WHERE project_id = ?', (project_id,))
        cursor.execute('DELETE FROM pm_developers WHERE project_id = ?', (project_id,))
        cursor.execute('DELETE FROM pm_projects WHERE id = ?', (project_id,))
        conn.commit()
    return jsonify({'status': 'deleted'})


# ========== 任务 CRUD API ==========

@tasks_bp.route('', methods=['GET'])
def get_tasks():
    """获取任务列表"""
    project_id = request.args.get('project_id', type=int)
    assignee_id = request.args.get('assignee_id', type=int)
    status = request.args.get('status')

    if project_id:
        tasks = TaskDAO.get_by_project(project_id, status=status, assignee_id=assignee_id)
    elif assignee_id:
        tasks = TaskDAO.get_by_assignee(assignee_id)
    else:
        # 返回所有任务（限制数量）
        with TaskDAO.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT t.*, p.name as project_name,
                       a.name as assignee_name
                FROM pm_tasks t
                LEFT JOIN pm_projects p ON t.project_id = p.id
                LEFT JOIN pm_developers a ON t.assignee_id = a.id
                ORDER BY t.priority DESC, t.created_at DESC
                LIMIT 100
            ''')
            tasks = [dict(row) for row in cursor.fetchall()]

    return jsonify(tasks)


@tasks_bp.route('/<int:task_id>', methods=['GET'])
def get_task(task_id):
    """获取任务详情"""
    task = TaskDAO.get_by_id(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    # 获取历史记录
    history = TaskHistoryDAO.get_by_task(task_id)
    task['history'] = history

    return jsonify(task)


@tasks_bp.route('', methods=['POST'])
def create_task():
    """创建任务"""
    data = request.json

    try:
        task = TaskService.create_task(
            project_id=data.get('project_id'),
            title=data.get('title'),
            description=data.get('description'),
            status=data.get('status', '待认领'),
            priority=data.get('priority', '中'),
            assignee_id=data.get('assignee_id'),
            reporter_id=data.get('reporter_id'),
            due_date=data.get('due_date'),
            depends_on=data.get('depends_on'),
            module=data.get('module')
        )
        return jsonify(task), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@tasks_bp.route('/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    """更新任务"""
    data = request.json
    changed_by = data.pop('changed_by', None)

    try:
        task = TaskService.update_task(task_id, changed_by=changed_by, **data)
        return jsonify(task)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@tasks_bp.route('/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    """删除任务"""
    if TaskDAO.delete(task_id):
        return jsonify({'status': 'deleted'})
    return jsonify({'error': '任务不存在'}), 404


# ========== 任务依赖管理 ==========

@tasks_bp.route('/<int:task_id>/depend', methods=['POST'])
def set_task_dependency(task_id):
    """设置任务依赖"""
    data = request.json
    depends_on = data.get('depends_on')

    if not depends_on:
        return jsonify({'error': '缺少依赖任务ID'}), 400

    # 验证依赖任务存在
    dep_task = TaskDAO.get_by_id(depends_on)
    if not dep_task:
        return jsonify({'error': '依赖任务不存在'}), 404

    # 检查循环依赖
    if TaskService._check_circular_dependency(task_id, depends_on):
        return jsonify({'error': '不能创建循环依赖'}), 400

    try:
        task = TaskService.update_task(
            task_id,
            changed_by=data.get('changed_by'),
            depends_on=depends_on
        )
        return jsonify(task)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@tasks_bp.route('/blocked', methods=['GET'])
def get_blocked_tasks():
    """获取被阻塞的任务"""
    project_id = request.args.get('project_id', type=int)
    blocked = TaskDAO.get_blocked_tasks(project_id)
    return jsonify(blocked)


@tasks_bp.route('/<int:task_id>/remind', methods=['POST'])
def send_reminder(task_id):
    """发送催促消息"""
    data = request.json
    sender_id = data.get('sender_id')

    if not sender_id:
        return jsonify({'error': '缺少发送者ID'}), 400

    try:
        message_id = TaskService.send_reminder(task_id, sender_id)
        return jsonify({'message_id': message_id, 'status': 'sent'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


# ========== 历史记录 API ==========

@tasks_bp.route('/<int:task_id>/history', methods=['GET'])
def get_task_history(task_id):
    """获取任务的历史记录"""
    history = TaskHistoryDAO.get_by_task(task_id)
    return jsonify(history)


# ========== 开发人员 API ==========

@tasks_bp.route('/developers', methods=['GET'])
def get_developers():
    """获取开发人员列表"""
    project_id = request.args.get('project_id', type=int)

    if project_id:
        developers = DeveloperDAO.get_by_project(project_id)
    else:
        developers = DeveloperDAO.get_all()

    return jsonify(developers)


@tasks_bp.route('/developers', methods=['POST'])
def create_developer():
    """创发发人员"""
    data = request.json

    try:
        dev_id = DeveloperDAO.create(
            name=data.get('name'),
            email=data.get('email'),
            git_name=data.get('git_name'),
            role=data.get('role', 'developer'),
            project_id=data.get('project_id')
        )
        return jsonify({'id': dev_id, 'name': data.get('name')}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@tasks_bp.route('/developers/<int:developer_id>', methods=['GET'])
def get_developer(developer_id):
    """获取开发人员详情"""
    developer = DeveloperDAO.get_by_id(developer_id)
    if not developer:
        return jsonify({'error': '开发人员不存在'}), 404

    # 获取该人员的任务统计
    tasks = TaskDAO.get_by_assignee(developer_id, include_blocked=False)
    stats = {
        'total': len(tasks),
        'pending': sum(1 for t in tasks if t['status'] == '待认领'),
        'in_progress': sum(1 for t in tasks if t['status'] == '开发中'),
        'completed': sum(1 for t in tasks if t['status'] == '已完成'),
        'blocked': sum(1 for t in tasks if t['status'] == '被阻塞')
    }

    developer['task_stats'] = stats
    return jsonify(developer)


@tasks_bp.route('/developers/<int:developer_id>', methods=['PUT'])
def update_developer(developer_id):
    """更新开发人员信息"""
    data = request.json

    if DeveloperDAO.update(developer_id, **data):
        return jsonify(DeveloperDAO.get_by_id(developer_id))
    return jsonify({'error': '更新失败'}), 400


# ========== 消息 API ==========

@tasks_bp.route('/messages', methods=['GET'])
def get_messages():
    """获取消息列表"""
    receiver_id = request.args.get('receiver_id', type=int)
    unread_only = request.args.get('unread_only', 'false').lower() == 'true'

    if not receiver_id:
        return jsonify({'error': '缺少接收者ID'}), 400

    messages = MessageDAO.get_by_receiver(receiver_id, unread_only=unread_only)
    unread_count = MessageDAO.get_unread_count(receiver_id)

    return jsonify({
        'messages': messages,
        'unread_count': unread_count
    })


@tasks_bp.route('/messages/<int:message_id>/read', methods=['POST'])
def mark_message_read(message_id):
    """标记消息为已读"""
    if MessageDAO.mark_as_read(message_id):
        return jsonify({'status': 'read'})
    return jsonify({'error': '消息不存在'}), 404


@tasks_bp.route('/messages/read-all', methods=['POST'])
def mark_all_messages_read():
    """标记所有消息为已读"""
    data = request.json
    receiver_id = data.get('receiver_id')

    if not receiver_id:
        return jsonify({'error': '缺少接收者ID'}), 400

    MessageDAO.mark_all_as_read(receiver_id)
    return jsonify({'status': 'all_read'})


# ========== Bug API ==========

@tasks_bp.route('/bugs', methods=['GET'])
def get_bugs():
    """获取Bug列表"""
    assignee_id = request.args.get('assignee_id', type=int)
    project_id = request.args.get('project_id', type=int)

    if assignee_id:
        bugs = BugDAO.get_by_assignee(assignee_id)
    else:
        bugs = BugDAO.get_open_bugs(project_id)

    return jsonify(bugs)


@tasks_bp.route('/bugs', methods=['POST'])
def create_bug():
    """创建Bug记录"""
    data = request.json

    try:
        bug_id = BugDAO.create(
            title=data.get('title'),
            description=data.get('description'),
            severity=data.get('severity', '中'),
            task_id=data.get('task_id'),
            reporter_id=data.get('reporter_id'),
            assignee_id=data.get('assignee_id'),
            git_commit_hash=data.get('git_commit_hash')
        )
        return jsonify({'id': bug_id}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@tasks_bp.route('/bugs/<int:bug_id>', methods=['PUT'])
def update_bug(bug_id):
    """更新Bug状态"""
    data = request.json

    if BugDAO.update(bug_id, **data):
        return jsonify({'status': 'updated'})
    return jsonify({'error': '更新失败'}), 400


# ========== 开发者仪表盘 API ==========

@tasks_bp.route('/dashboard/<int:developer_id>', methods=['GET'])
def get_developer_dashboard(developer_id):
    """获取开发者的仪表盘数据"""
    developer = DeveloperDAO.get_by_id(developer_id)
    if not developer:
        return jsonify({'error': '开发人员不存在'}), 404

    project_id = request.args.get('project_id', type=int)

    # 获取我的任务
    my_tasks_data = TaskService.get_my_tasks(developer_id, project_id=project_id)

    # 获取阻塞我的任务
    blocking_tasks = TaskService.get_blocking_tasks(developer_id, project_id=project_id)

    # 获取我的Bug
    my_bugs = BugDAO.get_by_assignee(developer_id) if not project_id else []

    # 获取我的消息
    my_messages = MessageDAO.get_by_receiver(developer_id, unread_only=False)
    unread_count = MessageDAO.get_unread_count(developer_id)

    return jsonify({
        'developer': developer,
        'tasks': my_tasks_data['tasks'],
        'task_stats': my_tasks_data['stats'],
        'blocking_tasks': blocking_tasks,
        'bugs': my_bugs,
        'messages': my_messages[:10],  # 只返回最近10条
        'unread_count': unread_count
    })


@tasks_bp.route('/dashboard/<int:developer_id>/tasks', methods=['GET'])
def get_my_tasks(developer_id):
    """获取我的任务列表"""
    my_tasks_data = TaskService.get_my_tasks(developer_id)
    return jsonify(my_tasks_data)


# ========== 批量操作 ==========

@tasks_bp.route('/batch-create', methods=['POST'])
def batch_create_tasks():
    """批量创建任务（用于Excel导入）"""
    data = request.json
    tasks_data = data.get('tasks', [])

    if not tasks_data:
        return jsonify({'error': '没有任务数据'}), 400

    created_tasks = []
    errors = []

    for i, task_data in enumerate(tasks_data):
        try:
            task = TaskService.create_task(
                project_id=task_data.get('project_id'),
                title=task_data.get('title'),
                description=task_data.get('description'),
                status=task_data.get('status', '待认领'),
                priority=task_data.get('priority', '中'),
                assignee_id=task_data.get('assignee_id'),
                due_date=task_data.get('due_date'),
                depends_on=task_data.get('depends_on'),
                module=task_data.get('module')
            )
            created_tasks.append(task)
        except Exception as e:
            errors.append({'index': i, 'error': str(e)})

    return jsonify({
        'created_count': len(created_tasks),
        'error_count': len(errors),
        'tasks': created_tasks,
        'errors': errors
    })


# ========== 任务统计 ==========

@tasks_bp.route('/stats/<int:project_id>', methods=['GET'])
def get_project_stats(project_id):
    """获取项目的统计信息"""
    project = ProjectDAO.get_with_stats(project_id)
    if not project:
        return jsonify({'error': '项目不存在'}), 404

    # 获取开发人员列表
    developers = DeveloperDAO.get_by_project(project_id)

    # 获取每个开发人员的任务统计
    dev_stats = []
    for dev in developers:
        tasks = TaskDAO.get_by_assignee(dev['id'])
        stats = {
            'developer': dev,
            'total': len(tasks),
            'by_status': {}
        }
        for task in tasks:
            status = task['status']
            stats['by_status'][status] = stats['by_status'].get(status, 0) + 1
        dev_stats.append(stats)

    return jsonify({
        'project': project,
        'developer_stats': dev_stats
    })


# 循环依赖检查辅助函数
def _check_circular_dependency(task_id: int, depends_on_id: int, visited: set = None) -> bool:
    """检查是否会形成循环依赖"""
    if visited is None:
        visited = set()

    if task_id == depends_on_id:
        return True

    if depends_on_id in visited:
        return False

    visited.add(depends_on_id)

    dep_task = TaskDAO.get_by_id(depends_on_id)
    if dep_task and dep_task.get('depends_on'):
        return _check_circular_dependency(task_id, dep_task['depends_on'], visited)

    return False


# 注册循环依赖检查函数
TaskService._check_circular_dependency = staticmethod(_check_circular_dependency)