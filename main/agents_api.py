#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能体 API - 提供智能体执行接口和状态查询
"""

import os
import json
from datetime import datetime
from flask import Blueprint, request, jsonify
from main.agents import (
    AgentScheduler, ProjectManagerAgent, ProgressTrackerAgent,
    TestExpertAgent, ArchitectAgent, call_llm
)
from main.agent_scheduler import (
    get_scheduler, start_scheduler, stop_scheduler, trigger_agent
)
from main.models import (
    ProjectDAO, DeveloperDAO, get_db_connection
)


# 创建蓝图
agents_bp = Blueprint('agents', __name__, url_prefix='/api/agents')


# ========== 智能体执行 API ==========

@agents_bp.route('/run', methods=['POST'])
def run_agent():
    """
    运行指定智能体
    请求体：
    {
        "agent": "progress_tracker|test_expert|project_manager|architect",
        "project_id": 1,
        "action": "daily_report|review|..."
    }
    """
    data = request.json
    agent_name = data.get('agent')
    project_id = data.get('project_id')
    action = data.get('action')

    if not agent_name or not project_id:
        return jsonify({'error': '缺少必要参数'}), 400

    try:
        result = trigger_agent(agent_name, project_id, action)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/run-all/<int:project_id>', methods=['POST'])
def run_all_agents(project_id):
    """运行所有智能体"""
    scheduler = get_scheduler()
    try:
        results = scheduler.run_all_agents(project_id)
        return jsonify({
            'success': True,
            'project_id': project_id,
            'results': results
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/daily-report/<int:project_id>', methods=['GET'])
def generate_daily_report(project_id):
    """生成项目日报"""
    pm = ProjectManagerAgent()
    try:
        result = pm.execute({'project_id': project_id, 'action': 'daily_report'})
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/risk-analysis/<int:project_id>', methods=['GET'])
def analyze_risks(project_id):
    """分析项目风险"""
    pm = ProjectManagerAgent()
    try:
        result = pm.execute({'project_id': project_id, 'action': 'risk_analysis'})
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/progress-track/<int:project_id>', methods=['GET'])
def track_progress(project_id):
    """追踪项目进度"""
    tracker = ProgressTrackerAgent()
    try:
        result = tracker.execute({'project_id': project_id})
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/test-expert/<int:project_id>', methods=['GET'])
def run_test_expert(project_id):
    """运行测试专家"""
    test_expert = TestExpertAgent()
    try:
        days = request.args.get('days', 1, type=int)
        result = test_expert.execute({'project_id': project_id, 'days': days})
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/architect/review', methods=['POST'])
def review_code():
    """代码审查"""
    data = request.json
    project_id = data.get('project_id')
    file_path = data.get('file_path')

    if not project_id:
        return jsonify({'error': '缺少项目ID'}), 400

    architect = ArchitectAgent()
    try:
        result = architect.execute({
            'action': 'review',
            'project_id': project_id,
            'file_path': file_path
        })
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/architect/suggest', methods=['POST'])
def suggest_architecture():
    """架构建议"""
    data = request.json
    project_id = data.get('project_id')
    requirements = data.get('requirements')

    if not requirements:
        return jsonify({'error': '缺少需求描述'}), 400

    architect = ArchitectAgent()
    try:
        result = architect.execute({
            'action': 'suggest',
            'project_id': project_id,
            'requirements': requirements
        })
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ========== 调度器控制 API ==========

@agents_bp.route('/scheduler/start', methods=['POST'])
def start_scheduler_api():
    """启动调度器"""
    try:
        start_scheduler()
        return jsonify({'status': 'started', 'message': '调度器已启动'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/scheduler/stop', methods=['POST'])
def stop_scheduler_api():
    """停止调度器"""
    try:
        stop_scheduler()
        return jsonify({'status': 'stopped', 'message': '调度器已停止'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/scheduler/status', methods=['GET'])
def scheduler_status():
    """获取调度器状态"""
    scheduler = get_scheduler()
    return jsonify({
        'running': scheduler.running,
        'last_run': scheduler.last_run
    })


# ========== 智能体日志 API ==========

@agents_bp.route('/logs', methods=['GET'])
def get_agent_logs():
    """获取智能体执行日志"""
    limit = request.args.get('limit', 50, type=int)
    agent_type = request.args.get('type')

    with get_db_connection() as conn:
        cursor = conn.cursor()

        if agent_type:
            cursor.execute('''
                SELECT * FROM pm_agent_logs
                WHERE agent_type = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (agent_type, limit))
        else:
            cursor.execute('''
                SELECT * FROM pm_agent_logs
                ORDER BY created_at DESC LIMIT ?
            ''', (limit,))

        rows = cursor.fetchall()
        return jsonify([dict(row) for row in rows])


@agents_bp.route('/logs/<int:project_id>', methods=['GET'])
def get_project_agent_logs(project_id):
    """获取项目的智能体日志"""
    limit = request.args.get('limit', 50, type=int)

    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 获取该项目相关的任务日志
        cursor.execute('''
            SELECT * FROM pm_agent_logs l
            WHERE l.task_id IN (SELECT id FROM pm_tasks WHERE project_id = ?)
               OR l.agent_type IN ('progress_tracker', 'test_expert', 'project_manager')
            ORDER BY l.created_at DESC LIMIT ?
        ''', (project_id, limit))

        rows = cursor.fetchall()
        return jsonify([dict(row) for row in rows])


# ========== 批量操作 ==========

@agents_bp.route('/batch-daily-report', methods=['POST'])
def batch_daily_report():
    """为所有项目生成日报"""
    scheduler = get_scheduler()
    try:
        results = scheduler.daily_report_all_projects()
        return jsonify({
            'success': True,
            'results': results
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@agents_bp.route('/batch-progress-track', methods=['POST'])
def batch_progress_track():
    """追踪所有项目进度"""
    projects = ProjectDAO.get_all()
    results = {}

    scheduler = get_scheduler()
    for project in projects:
        try:
            result = scheduler.run_project_agent('progress_tracker', project['id'])
            results[project['id']] = result
        except Exception as e:
            results[project['id']] = {'error': str(e)}

    return jsonify({
        'success': True,
        'results': results
    })


# ========== 对话式Agent交互 ==========

@agents_bp.route('/chat', methods=['POST'])
def agent_chat():
    """
    与智能体对话
    请求体：
    {
        "developer_id": 1,
        "project_id": 1,
        "message": "帮我分析一下这个项目的风险"
    }
    """
    data = request.json
    developer_id = data.get('developer_id')
    project_id = data.get('project_id')
    message = data.get('message', '')

    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    # 分析意图
    lower_msg = message.lower()

    if any(kw in lower_msg for kw in ['风险', 'risk']):
        agent = ProjectManagerAgent()
        result = agent.execute({'project_id': project_id, 'action': 'risk_analysis'})
        reply = result.get('analysis', '风险分析完成')

    elif any(kw in lower_msg for kw in ['进度', 'progress', '状态']):
        agent = ProgressTrackerAgent()
        result = agent.execute({'project_id': project_id})
        reply = result.get('report', '进度追踪完成')

    elif any(kw in lower_msg for kw in ['bug', '测试', 'test']):
        agent = TestExpertAgent()
        result = agent.execute({'project_id': project_id, 'days': 1})
        reply = result.get('report', '测试分析完成')

    elif any(kw in lower_msg for kw in ['日报', '报告', 'report']):
        agent = ProjectManagerAgent()
        result = agent.execute({'project_id': project_id, 'action': 'daily_report'})
        reply = result.get('report', '日报生成完成')

    elif any(kw in lower_msg for kw in ['架构', 'architecture']):
        reply = "请提供您的需求描述，例如：'帮我设计一个用户系统的架构'"

    else:
        # 默认使用项目经理
        agent = ProjectManagerAgent()
        result = agent.execute({'project_id': project_id, 'action': 'coordinate'})
        reply = "我已协调各智能体完成分析，请查看项目状态"

    # 保存对话历史
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO pm_chat_history (developer_id, project_id, role, content)
            VALUES (?, ?, ?, ?)
        ''', (developer_id, project_id, 'assistant', reply))

    return jsonify({
        'success': True,
        'reply': reply
    })


# ========== 初始化 ==========

def init_agents():
    """初始化智能体系统"""
    # 确保调度器已启动
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
    print("[AgentSystem] Initialized")


if __name__ == '__main__':
    init_agents()