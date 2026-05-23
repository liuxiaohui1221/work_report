#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI对话服务 - 任务解析、代码生成、Human-in-the-loop审核
"""

import os
import json
import subprocess
import re
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
from main.models import (
    DeveloperDAO, ProjectDAO, TaskDAO, TaskService,
    MessageDAO, ChatService, get_db_connection
)


# 创建蓝图
ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')


# ========== LLM 调用 ==========

def call_llm(prompt: str, system: str = None) -> str:
    """调用配置的LLM生成响应"""
    # 获取LLM配置
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM llm_config WHERE is_active=1 ORDER BY id DESC LIMIT 1')
        row = cursor.fetchone()

    if not row:
        return jsonify({'error': '未配置LLM'}), 500

    config = dict(row)
    api_key = config.get('api_key')
    base_url = config.get('base_url', 'https://api.minimaxi.com/anthropic')
    model = config.get('model_name', 'MiniMax-M2.7')
    max_tokens = config.get('max_tokens', 10000)
    temperature = config.get('temperature', 0.5)

    if not api_key:
        return jsonify({'error': 'LLM API Key未配置'}), 500

    try:
        import anthropic
        client = anthropic.Anthropic(
            base_url=base_url if base_url else None,
            api_key=api_key
        )

        messages = []
        if system:
            messages.append({"role": "user", "content": system + "\n\n" + prompt})
        else:
            messages.append({"role": "user", "content": prompt})

        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=messages
        )

        # Handle response content - could be TextBlock or ThinkingBlock
        result_text = ""
        for content_block in response.content:
            if hasattr(content_block, 'text') and content_block.text:
                result_text += content_block.text
            elif hasattr(content_block, 'thinking') and content_block.thinking:
                result_text += f"[思考: {content_block.thinking[:200]}...]"
        return result_text if result_text else "LLM返回空内容"

    except Exception as e:
        return f"LLM调用失败: {str(e)}"


# ========== 任务解析 ==========

TASK_PARSE_PROMPT = """你是一个任务解析助手。用户可能用自然语言描述任务，请提取以下信息：

1. 意图识别：
   - "添加任务" / "创建任务" / "新任务" → create_task
   - "查询进度" / "看看进度" → query_progress
   - "帮我写代码" / "生成代码" / "修改代码" → generate_code
   - "催促" / "提醒" → send_reminder
   - 其他 → general_chat

2. 任务信息提取：
   - title: 任务标题
   - description: 任务描述
   - project: 项目名称
   - assignee: 负责人
   - due_date: 截止日期
   - priority: 优先级 (低/中/高/紧急)

请返回JSON格式：
{
    "intent": "create_task|query_progress|generate_code|send_reminder|general_chat",
    "task": {
        "title": "...",
        "description": "...",
        "project": "...",
        "assignee": "...",
        "due_date": "...",
        "priority": "..."
    },
    "reply": "对用户的回复内容"
}
"""


def parse_user_intent(message: str, developer_id: int = None) -> dict:
    """解析用户消息意图"""
    response = call_llm(message, system=TASK_PARSE_PROMPT)

    try:
        # 尝试解析JSON
        # 提取JSON部分（可能包含在markdown代码块中）
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            result = json.loads(json_match.group())
            return result
        else:
            return {'intent': 'general_chat', 'raw_response': response}
    except:
        return {'intent': 'general_chat', 'raw_response': response}


# ========== 代码生成 ==========

CODE_GEN_PROMPT = """你是一个代码生成助手。用户需要为项目生成代码修改。

请遵循以下规则：
1. 只生成代码，不要解释
2. 使用清晰的注释说明修改目的
3. 对于每个文件，说明：
   - 文件路径（相对于项目根目录）
   - 修改类型：create/replace/append
   - 完整文件内容（如果是新建或替换）

输出格式：
```json
{
    "files": [
        {
            "path": "src/utils/helper.js",
            "action": "create|replace|append",
            "content": "...完整代码..."
        }
    ],
    "summary": "修改摘要"
}
```
```"""


def generate_code_for_task(task_description: str, project_id: int = None) -> dict:
    """根据任务描述生成代码"""
    # 获取项目信息
    project = None
    if project_id:
        project = ProjectDAO.get_by_id(project_id)
        repo_path = project.get('repo_path') if project else None
    else:
        # 获取第一个有repo_path的项目
        projects = ProjectDAO.get_all()
        for p in projects:
            if p.get('repo_path'):
                repo_path = p['repo_path']
                project = p
                break

    # 获取项目结构信息
    project_info = ""
    if repo_path and os.path.exists(repo_path):
        try:
            # 获取主要目录结构
            result = subprocess.run(
                ["git", "-C", repo_path, "ls-files", "--directory", "-o"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=10
            )
            project_info = f"项目路径: {repo_path}\n主要文件:\n{result.stdout[:2000]}"
        except:
            project_info = f"项目路径: {repo_path}"

    prompt = f"""
任务描述: {task_description}

项目信息:
{project_info}

请根据任务描述生成相应的代码修改。
"""

    response = call_llm(prompt, system=CODE_GEN_PROMPT)

    # 解析响应
    try:
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            result = json.loads(json_match.group())
            return result
        else:
            return {'error': '无法解析代码生成结果', 'raw': response}
    except Exception as e:
        return {'error': f'解析失败: {str(e)}', 'raw': response}


# ========== 待审核代码存储 ==========

def save_pending_code(developer_id: int, project_id: int,
                      files: list, task_description: str) -> int:
    """保存待审核的代码修改"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO pm_pending_codes
            (developer_id, project_id, files_json, task_description, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)
        ''', (developer_id, project_id, json.dumps(files, ensure_ascii=False), task_description))
        conn.commit()
        return cursor.lastrowid


def get_pending_code(code_id: int) -> dict:
    """获取待审核代码"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM pm_pending_codes WHERE id = ?', (code_id,))
        row = cursor.fetchone()
        if not row:
            return None

        result = dict(row)
        result['files'] = json.loads(result.get('files_json', '[]'))
        return result


def approve_pending_code(code_id: int) -> dict:
    """批准并应用代码修改"""
    pending = get_pending_code(code_id)
    if not pending:
        return {'error': '代码不存在'}

    project = ProjectDAO.get_by_id(pending['project_id'])
    if not project or not project.get('repo_path'):
        return {'error': '项目路径未配置'}

    repo_path = project['repo_path']
    results = []

    for file_info in pending['files']:
        file_path = os.path.join(repo_path, file_info['path'])
        action = file_info.get('action', 'replace')

        try:
            if action == 'create':
                # 确保目录存在
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(file_info['content'])
                results.append({'path': file_info['path'], 'status': 'created'})

            elif action == 'replace':
                # 备份原文件
                if os.path.exists(file_path):
                    backup_path = file_path + '.bak'
                    os.rename(file_path, backup_path)
                # 写入新内容
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(file_info['content'])
                results.append({'path': file_info['path'], 'status': 'replaced'})

            elif action == 'append':
                with open(file_path, 'a', encoding='utf-8') as f:
                    f.write('\n' + file_info['content'])
                results.append({'path': file_info['path'], 'status': 'appended'})

        except Exception as e:
            results.append({'path': file_info['path'], 'status': 'error', 'error': str(e)})

    # 更新状态
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE pm_pending_codes
            SET status = 'approved', applied_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (code_id,))
        conn.commit()

    return {
        'approved': True,
        'results': results,
        'applied_count': sum(1 for r in results if r['status'] != 'error')
    }


def reject_pending_code(code_id: int) -> bool:
    """拒绝代码修改"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE pm_pending_codes
            SET status = 'rejected', applied_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (code_id,))
        conn.commit()
        return cursor.rowcount > 0


# ========== API 端点 ==========

@ai_bp.route('/chat', methods=['POST'])
def chat():
    """
    AI对话入口 - 支持多Tab并行
    请求体：
    {
        "developer_id": 1,
        "project_id": 1,
        "session_id": "uuid-for-this-tab",
        "message": "帮我添加一个任务：完成用户登录功能"
    }
    """
    data = request.json
    developer_id = data.get('developer_id')
    project_id = data.get('project_id')
    session_id = data.get('session_id')  # Tab会话ID
    message = data.get('message', '')

    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    # 如果没有session_id，创建一个
    if not session_id:
        from main.coordination import SessionManager
        session_id = SessionManager.create_session(developer_id, project_id)

    # 更新会话活跃时间
    from main.coordination import SessionManager
    SessionManager.update_session(session_id, project_id=project_id)

    # 解析用户意图
    parsed = parse_user_intent(message, developer_id)
    intent = parsed.get('intent', 'general_chat')

    # 保存对话历史
    ChatService.save_chat(developer_id, project_id, 'user', message, session_id=session_id)

    # 根据意图处理
    if intent == 'create_task':
        # 创建任务
        task_info = parsed.get('task', {})
        project_name = task_info.get('project', '')

        # 查找项目
        if not project_id and project_name:
            projects = ProjectDAO.get_all()
            for p in projects:
                if project_name.lower() in p['name'].lower():
                    project_id = p['id']
                    break

        if not project_id:
            return jsonify({
                'intent': 'create_task',
                'reply': parsed.get('reply', '好的，请告诉我项目名称'),
                'need_project': True,
                'session_id': session_id
            })

        # 获取开发者信息
        developer = DeveloperDAO.get_by_id(developer_id)

        # 查找负责人
        assignee_name = task_info.get('assignee', '')
        assignee_id = None
        if assignee_name:
            developers = DeveloperDAO.get_by_project(project_id)
            for dev in developers:
                if assignee_name in dev['name'] or dev['name'] in assignee_name:
                    assignee_id = dev['id']
                    break

        try:
            task = TaskService.create_task(
                project_id=project_id,
                title=task_info.get('title', message),
                description=task_info.get('description', ''),
                priority=task_info.get('priority', '中'),
                assignee_id=assignee_id,
                reporter_id=developer_id,
                due_date=task_info.get('due_date')
            )
            reply = f"✅ 任务已创建！\n\n【{task['title']}】\n状态：{task['status']}\n优先级：{task['priority']}"
            if task.get('assignee_name'):
                reply += f"\n负责人：{task['assignee_name']}"

        except Exception as e:
            reply = f"❌ 创建任务失败：{str(e)}"

        ChatService.save_chat(developer_id, project_id, 'assistant', reply, session_id=session_id)

        return jsonify({
            'intent': 'create_task',
            'task': task if 'task' in locals() else None,
            'reply': reply,
            'session_id': session_id
        })

    elif intent == 'generate_code':
        # 代码生成 - 使用异步方式避免阻塞
        task_description = parsed.get('task', {}).get('description', message)

        # 先检查文件锁
        from main.coordination import CodeLockManager, AgentTaskCoordinator, get_code_generator

        # 生成代码（同步，但可以在前端显示加载状态）
        try:
            code_result = generate_code_for_task(task_description, project_id)

            if 'error' in code_result:
                return jsonify({
                    'intent': 'generate_code',
                    'reply': f"❌ 代码生成失败：{code_result['error']}",
                    'session_id': session_id
                })

            files = code_result.get('files', [])

            # 检查文件锁
            locked_files = []
            for f in files:
                success, lock_info = CodeLockManager.acquire_lock(
                    project_id, f['path'], session_id, developer_id, ttl_minutes=60
                )
                if not success:
                    locked_files.append({'path': f['path'], 'locked_by': lock_info.get('session_id')})

            # 如果有被锁的文件，告知用户
            if locked_files:
                locked_info = ", ".join([f"{f['path']}(被其他会话占用)" for f in locked_files])
                warning = f"\n\n⚠️ 以下文件正被其他Tab操作，无法同时修改：{locked_info}"

                # 仍然可以生成，只是不能应用被锁的文件
                code_id = save_pending_code(
                    developer_id,
                    project_id,
                    [f for f in files if f['path'] not in [lf['path'] for lf in locked_files]],
                    task_description
                )

                reply = f"""🤖 代码已生成，但部分文件被锁定。

{warning}

可修改的文件：
"""
                for f in files:
                    if f['path'] not in [lf['path'] for lf in locked_files]:
                        reply += f"  - {f['path']}\n"

                reply += f"""
📋 代码ID: {code_id}

请等待锁定释放后再应用，或联系相关人员确认。
"""

                return jsonify({
                    'intent': 'generate_code',
                    'code_id': code_id,
                    'files': [f for f in files if f['path'] not in [lf['path'] for lf in locked_files]],
                    'locked_files': locked_files,
                    'summary': code_result.get('summary', ''),
                    'reply': reply,
                    'session_id': session_id
                })

            # 保存待审核代码
            code_id = save_pending_code(developer_id, project_id, files, task_description)

            reply = f"""🤖 代码已生成，等待您的审核。

修改摘要：{code_result.get('summary', '见下方详情')}

涉及文件：
"""
            for f in files:
                reply += f"  - {f['path']} ({f.get('action', 'replace')})\n"

            reply += f"""
📋 代码ID: {code_id}
🆔 会话ID: {session_id}

请查看代码详情，然后：
- ✅ 确认应用
- ❌ 取消修改
- 💬 提出修改意见
"""

            # 记录Agent任务
            AgentTaskCoordinator.create_task(
                task_type='code_generation',
                description=task_description,
                project_id=project_id,
                developer_id=developer_id,
                session_id=session_id,
                priority=1
            )

            return jsonify({
                'intent': 'generate_code',
                'code_id': code_id,
                'files': files,
                'summary': code_result.get('summary', ''),
                'reply': reply,
                'session_id': session_id
            })

        except Exception as e:
            return jsonify({
                'intent': 'generate_code',
                'reply': f"❌ 代码生成失败：{str(e)}",
                'session_id': session_id
            })

    elif intent == 'query_progress':
        # 查询进度
        if not developer_id:
            return jsonify({'intent': 'query_progress', 'reply': '请先登录'})

        tasks_data = TaskService.get_my_tasks(developer_id)
        stats = tasks_data['stats']

        reply = f"""📊 您的任务进度

总计：{stats['total']} 个任务
- ⏳ 待认领：{stats['pending']}
- 🔨 开发中：{stats['in_progress']}
- 🚫 被阻塞：{stats['blocked']}
- ✅ 已完成：{stats['completed']}

完成率：{round(stats['completed']/stats['total']*100, 1) if stats['total'] > 0 else 0}%
"""

        # 列出阻塞的任务
        blockers = tasks_data.get('blockers', [])
        if blockers:
            reply += f"\n🚧 阻塞您的任务（{len(blockers)}个）：\n"
            for b in blockers[:5]:
                reply += f"  - [{b['status']}] {b['title']} (负责人: {b.get('assignee_name', '未知')})\n"

        return jsonify({
            'intent': 'query_progress',
            'stats': stats,
            'reply': reply
        })

    elif intent == 'send_reminder':
        # 发送催促
        task_description = parsed.get('task', {}).get('description', '')
        if not task_description:
            return jsonify({
                'intent': 'send_reminder',
                'reply': '请告诉我要催促哪个任务'
            })

        # 查找对应任务
        tasks = TaskDAO.get_by_assignee(developer_id)
        target_task = None
        for t in tasks:
            if task_description in t.get('title', '') or t.get('title', '') in task_description:
                target_task = t
                break

        if not target_task:
            return jsonify({
                'intent': 'send_reminder',
                'reply': '未找到对应的任务'
            })

        try:
            message_id = TaskService.send_reminder(target_task['id'], developer_id)
            reply = f"✅ 催促消息已发送！\n\n任务：{target_task['title']}"
        except ValueError as e:
            reply = f"❌ {str(e)}"

        return jsonify({
            'intent': 'send_reminder',
            'reply': reply
        })

    else:
        # 通用对话
        # 调用LLM进行对话
        context = ""
        if developer_id:
            developer = DeveloperDAO.get_by_id(developer_id)
            if developer:
                context += f"当前用户：{developer['name']}\n"

        if project_id:
            project = ProjectDAO.get_by_id(project_id)
            if project:
                context += f"当前项目：{project['name']}\n"

        full_prompt = f"{context}\n用户消息：{message}"
        response = call_llm(full_prompt)

        ChatService.save_chat(developer_id, project_id, 'assistant', response)

        return jsonify({
            'intent': 'general_chat',
            'reply': response
        })


@ai_bp.route('/code/<int:code_id>', methods=['GET'])
def get_pending_code_detail(code_id):
    """获取待审核代码详情"""
    pending = get_pending_code(code_id)
    if not pending:
        return jsonify({'error': '代码不存在'}), 404
    return jsonify(pending)


@ai_bp.route('/code/<int:code_id>/approve', methods=['POST'])
def approve_code(code_id):
    """批准代码修改"""
    data = request.json
    developer_id = data.get('developer_id')

    if not developer_id:
        return jsonify({'error': '缺少用户ID'}), 400

    result = approve_pending_code(code_id)
    if 'error' in result:
        return jsonify(result), 400

    # 记录操作
    ChatService.save_chat(
        developer_id, None, 'system',
        f"代码修改已应用：{result['applied_count']}个文件"
    )

    return jsonify({
        'success': True,
        'results': result['results']
    })


@ai_bp.route('/code/<int:code_id>/reject', methods=['POST'])
def reject_code(code_id):
    """拒绝代码修改"""
    data = request.json
    developer_id = data.get('developer_id')

    if reject_pending_code(code_id):
        ChatService.save_chat(
            developer_id, None, 'system',
            "代码修改已取消"
        )
        return jsonify({'success': True, 'message': '已取消代码修改'})
    return jsonify({'error': '操作失败'}), 400


@ai_bp.route('/code/<int:code_id>/modify', methods=['POST'])
def modify_code(code_id):
    """
    修改代码（用户提出修改意见后重新生成）
    请求体：
    {
        "developer_id": 1,
        "feedback": "把这个函数改名为 xxx"
    }
    """
    pending = get_pending_code(code_id)
    if not pending:
        return jsonify({'error': '代码不存在'}), 400

    data = request.json
    feedback = data.get('feedback', '')

    # 基于反馈重新生成
    task_description = f"原始需求：{pending['task_description']}\n\n修改意见：{feedback}"
    code_result = generate_code_for_task(task_description, pending['project_id'])

    if 'error' in code_result:
        return jsonify({
            'error': f"重新生成失败：{code_result['error']}"
        }), 400

    # 更新待审核代码
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE pm_pending_codes
            SET files_json = ?, task_description = ?, status = 'pending'
            WHERE id = ?
        ''', (json.dumps(code_result.get('files', []), ensure_ascii=False),
              task_description, code_id))
        conn.commit()

    return jsonify({
        'success': True,
        'code_id': code_id,
        'files': code_result.get('files', []),
        'summary': code_result.get('summary', '')
    })


@ai_bp.route('/history/<int:developer_id>', methods=['GET'])
def get_chat_history(developer_id):
    """获取对话历史"""
    project_id = request.args.get('project_id', type=int)
    limit = request.args.get('limit', 50, type=int)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        if project_id:
            cursor.execute('''
                SELECT * FROM pm_chat_history
                WHERE developer_id = ? AND project_id = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (developer_id, project_id, limit))
        else:
            cursor.execute('''
                SELECT * FROM pm_chat_history
                WHERE developer_id = ?
                ORDER BY created_at DESC LIMIT ?
            ''', (developer_id, limit))

        rows = cursor.fetchall()
        return jsonify([dict(row) for row in rows])


@ai_bp.route('/pending-codes', methods=['GET'])
def get_pending_codes():
    """获取当前用户的待审核代码"""
    developer_id = request.args.get('developer_id', type=int)
    if not developer_id:
        return jsonify({'error': '缺少用户ID'}), 400

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, project_id, task_description, status, created_at
            FROM pm_pending_codes
            WHERE developer_id = ? AND status = 'pending'
            ORDER BY created_at DESC
        ''', (developer_id,))
        rows = cursor.fetchall()
        return jsonify([dict(row) for row in rows])


# ========== 初始化数据库表 ==========

def init_pending_codes_table():
    """初始化待审核代码表"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pm_pending_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                developer_id INTEGER,
                project_id INTEGER,
                files_json TEXT,
                task_description TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                applied_at TIMESTAMP,
                FOREIGN KEY (developer_id) REFERENCES pm_developers(id),
                FOREIGN KEY (project_id) REFERENCES pm_projects(id)
            )
        ''')
        conn.commit()


if __name__ == '__main__':
    init_pending_codes_table()


# ========== 流式对话端点 ==========

def get_llm_config_dict():
    """获取LLM配置（dict格式，内部使用）"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM llm_config WHERE is_active=1 ORDER BY id DESC LIMIT 1')
        row = cursor.fetchone()
        if row:
            return dict(row)
    return {
        "provider": "minimax",
        "api_key": "",
        "base_url": "https://api.minimaxi.com/anthropic",
        "model_name": "MiniMax-M2.7"
    }


@ai_bp.route('/chat/stream', methods=['POST'])
def chat_stream():
    """
    流式AI对话入口 - 支持thinking block分离
    """
    data = request.json
    developer_id = data.get('developer_id')
    project_id = data.get('project_id')
    session_id = data.get('session_id')
    message = data.get('message', '')

    if not message:
        return jsonify({'error': '消息不能为空'}), 400

    # 如果没有session_id，创建一个
    if not session_id:
        from main.coordination import SessionManager
        session_id = SessionManager.create_session(developer_id, project_id)

    # 更新会话活跃时间
    from main.coordination import SessionManager
    SessionManager.update_session(session_id, project_id=project_id)

    # 保存用户消息
    ChatService.save_chat(developer_id, project_id, 'user', message, session_id=session_id)

    # 解析用户意图
    parsed = parse_user_intent(message, developer_id)
    intent = parsed.get('intent', 'general_chat')

    def generate():
        import json

        # 首先发送意图
        yield f"data: {json.dumps({'type': 'intent', 'value': intent})}\n\n"

        if intent == 'general_chat':
            # 使用流式LLM调用
            developer = DeveloperDAO.get_by_id(developer_id)
            username = developer.get('name', '开发者') if developer else '开发者'

            # 构建提示
            prompt = f"当前用户：{username}\n\n用户消息：{message}"

            # 获取LLM配置
            config = get_llm_config_dict()
            api_key = config.get('api_key', '')
            base_url = config.get('base_url', 'https://api.minimaxi.com/anthropic')
            model = config.get('model_name', 'MiniMax-M2.7')

            if not api_key:
                yield f"data: {json.dumps({'type': 'error', 'content': '请先配置API Key'})}\n\n"
                return

            try:
                import anthropic
                client = anthropic.Anthropic(base_url=base_url if base_url else None, api_key=api_key)

                messages = [{"role": "user", "content": prompt}]

                # 使用text_stream获取流式输出
                with client.messages.stream(
                    model=model,
                    max_tokens=8192,
                    messages=messages
                ) as stream:
                    for text in stream.text_stream:
                        yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"

                    # 发送完成信号
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': f'LLM调用失败: {str(e)}'})}\n\n"

        else:
            # 非通用意图（create_task, query_progress, generate_code, send_reminder）
            # 先发送处理中状态
            yield f"data: {json.dumps({'type': 'thinking_start'})}\n\n"

            if intent == 'create_task':
                # 解析任务信息，返回给用户确认
                task_info = parsed.get('task', {})

                # 检查是否有足够信息
                title = task_info.get('title', '')
                if not title or title == message:
                    # 信息不足，让用户补充
                    yield f"data: {json.dumps({'type': 'text', 'content': '🤔 请告诉我更多关于这个任务的信息，比如：\n• 任务标题是什么？\n• 具体要做什么？\n• 有截止日期吗？'})}\n\n"
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    return

                # 返回确认信息
                project_name = ''
                effective_project_id = project_id

                # 如果没有project_id，尝试使用开发者关联的项目
                if not effective_project_id:
                    devs = DeveloperDAO.get_by_project(None)  # 需要找个方式获取默认项目
                    # 简单处理：获取第一个项目
                    projects = ProjectDAO.get_all()
                    if projects:
                        effective_project_id = projects[0]['id']
                        project_name = projects[0]['name']
                else:
                    project = ProjectDAO.get_by_id(project_id)
                    if project:
                        project_name = project.get('name', '')

                yield f"data: {json.dumps({'type': 'task_preview', 'task': {
                    'title': title,
                    'description': task_info.get('description', ''),
                    'priority': task_info.get('priority', '中'),
                    'due_date': task_info.get('due_date', ''),
                    'project_name': project_name,
                    'project_id': effective_project_id
                }})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

            elif intent == 'query_progress':
                tasks_data = TaskService.get_my_tasks(developer_id, project_id=project_id)
                stats = tasks_data['stats']
                reply = f"""📊 您的任务进度

总计：{stats['total']} 个任务
- ⏳ 待认领：{stats['pending']}
- 🔨 开发中：{stats['in_progress']}
- 🚫 被阻塞：{stats['blocked']}
- ✅ 已完成：{stats['completed']}

完成率：{round(stats['completed']/stats['total']*100, 1) if stats['total'] > 0 else 0}%
"""
                yield f"data: {json.dumps({'type': 'text', 'content': reply})}\n\n"

            elif intent == 'send_reminder':
                from main.models import TaskDAO
                blockers = TaskDAO.get_my_blockers(developer_id, project_id)
                if blockers:
                    for b in blockers[:3]:
                        from main.models import MessageDAO, UserDAO
                        msg = f"🚨 提醒：您有一个阻塞任务 [{b['title']}] 需要关注"
                        MessageDAO.create(b['assignee_id'], developer_id, b['id'], msg)
                    yield f"data: {json.dumps({'type': 'text', 'content': f'✅ 已发送 {len(blockers[:3])} 条催促消息'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'text', 'content': '✅ 当前没有阻塞您的任务'})}\n\n"

            else:
                yield f"data: {json.dumps({'type': 'text', 'content': parsed.get('reply', '处理中...')})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(generate(), mimetype='text/event-stream')