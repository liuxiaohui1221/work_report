#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工作汇报系统 - Flask后端API
提供项目管理、Git配置、报告生成等RESTful API
"""

import os
import sys
import sqlite3
import json
import subprocess
import shutil
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from main import app_config
from main.models import init_task_db, get_db_connection
from main.tasks_api import tasks_bp
from main.excel_api import excel_bp
from main.ai_chat import ai_bp, init_pending_codes_table
from main.agents_api import agents_bp, init_agents
from main.coordination_api import coord_bp, init_coordination

# 初始化Flask应用
app = Flask(__name__, static_folder='../web', static_url_path='')
CORS(app)

app.config['UPLOAD_FOLDER'] = app_config.PLAN_DATA_DIR
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

# 数据库初始化
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work_report.db")

# 初始化任务管理数据库
init_task_db()

# 注册蓝图
app.register_blueprint(tasks_bp)
app.register_blueprint(excel_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(agents_bp)
app.register_blueprint(coord_bp)

# 初始化待审核代码表
init_pending_codes_table()

# 初始化并启动智能体调度器
init_agents()

# 初始化协调服务
init_coordination()


def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 项目配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            plan_dir TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Git项目表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS git_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 团队成员表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS team_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            git_name TEXT,
            email TEXT NOT NULL,
            role TEXT DEFAULT 'developer',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 定时任务表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            task_type TEXT NOT NULL,
            schedule TEXT NOT NULL,
            projects TEXT,
            time_range TEXT,
            recipients TEXT,
            is_active INTEGER DEFAULT 1,
            last_run TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 报告生成记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS report_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL,
            time_range TEXT NOT NULL,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            report_path TEXT,
            status TEXT,
            error_message TEXT
        )
    ''')

    # LLM配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS llm_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL DEFAULT 'minimax',
            api_key TEXT,
            base_url TEXT DEFAULT 'https://api.minimaxi.com/anthropic',
            model_name TEXT DEFAULT 'MiniMax-M2.7',
            max_tokens INTEGER DEFAULT 10000,
            temperature REAL DEFAULT 0.5,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ==================== 辅助函数 ====================

def parse_git_authors(project_path: str, since: str = None, until: str = None) -> list:
    """从Git仓库获取作者列表"""
    if not os.path.exists(project_path):
        return []

    cmd = [
        "git", "-C", project_path, "log",
        "--pretty=format:%an|%ae|%an",
        "--date=short"
    ]

    if since:
        cmd.insert(4, f"--since={since}")
    if until:
        cmd.insert(4, f"--until={until}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
            authors = {}
            for line in lines:
                parts = line.split("|")
                if len(parts) >= 3:
                    name, email, git_name = parts[0], parts[1], parts[2]
                    key = f"{name}|{email}"
                    if key not in authors:
                        authors[key] = {"name": name, "email": email, "git_name": git_name}
            return list(authors.values())
        return []
    except Exception as e:
        print(f"获取Git作者异常: {e}")
        return []


def parse_excel_tasks(filepath: str) -> list:
    """解析Excel任务文件"""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
        sheet = wb.active
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return []

        headers = [str(c).strip() if c else "" for c in rows[0]]
        col_map = {}
        for idx, h in enumerate(headers):
            h_lower = h.lower()
            if "模块" in h or "名称" in h:
                col_map["module"] = idx
            elif ("功能" in h or "描述" in h) and "功能" not in col_map:
                col_map["description"] = idx
            elif "状态" in h and "backend" not in col_map:
                col_map["backend_status"] = idx

        tasks = []
        for row_idx, row in enumerate(rows[1:], start=2):
            row_data = {}
            row_data["row"] = row_idx
            row_data["module"] = str(row[col_map.get("module", 0)]).strip() if col_map.get("module") is not None and col_map.get("module", 0) < len(row) else ""
            row_data["description"] = str(row[col_map.get("description", 1)]).strip() if col_map.get("description") is not None and col_map.get("description", 1) < len(row) else ""
            row_data["status"] = str(row[col_map.get("backend_status", 2)]).strip() if col_map.get("backend_status") is not None and col_map.get("backend_status", 2) < len(row) else ""
            if row_data["module"] or row_data["description"]:
                tasks.append(row_data)
        return tasks
    except Exception as e:
        return []


def get_git_commits(project_path: str, since: str = None, until: str = None) -> list:
    """获取Git提交记录"""
    if not os.path.exists(project_path):
        return []

    cmd = [
        "git", "-C", project_path, "log",
        "--pretty=format:%H|%s|%an|%ad",
        "--date=short"
    ]

    if since:
        cmd.insert(4, f"--since={since}")
    if until:
        cmd.insert(4, f"--until={until}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
            commits = []
            for line in lines:
                parts = line.split("|", 3)
                if len(parts) >= 4:
                    commits.append({
                        "hash": parts[0][:12],
                        "message": parts[1],
                        "author": parts[2],
                        "date": parts[3]
                    })
            return commits
        return []
    except Exception as e:
        print(f"获取Git提交异常: {e}")
        return []


# ==================== 项目管理API ====================

@app.route('/api/projects', methods=['GET'])
def get_projects():
    """获取项目列表"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM projects ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route('/api/projects', methods=['POST'])
def create_project():
    """创建项目配置"""
    data = request.json
    name = data.get('name')
    repo_path = data.get('repo_path')
    plan_dir = data.get('plan_dir', '')

    if not name or not repo_path:
        return jsonify({"error": "项目名称和Git路径不能为空"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO projects (name, repo_path, plan_dir) VALUES (?, ?, ?)',
        (name, repo_path, plan_dir)
    )
    conn.commit()
    project_id = cursor.lastrowid
    conn.close()

    return jsonify({"id": project_id, "name": name, "repo_path": repo_path}), 201


@app.route('/api/projects/<int:project_id>', methods=['PUT'])
def update_project(project_id):
    """更新项目配置"""
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE projects SET name=?, repo_path=?, plan_dir=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
        (data.get('name'), data.get('repo_path'), data.get('plan_dir'), project_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})


@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    """删除项目配置"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM projects WHERE id=?', (project_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


# ==================== Excel文件管理API ====================

@app.route('/api/excel/upload', methods=['POST'])
def upload_excel():
    """上传Excel任务文件"""
    if 'file' not in request.files:
        return jsonify({"error": "没有文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "没有选择文件"}), 400

    if file and file.filename.endswith('.xlsx'):
        filename = secure_filename(file.filename)
        project = request.form.get('project', 'default')
        project_dir = os.path.join(app.config['UPLOAD_FOLDER'], project)
        os.makedirs(project_dir, exist_ok=True)

        filepath = os.path.join(project_dir, filename)
        file.save(filepath)

        # 解析任务文件
        tasks = parse_excel_tasks(filepath)

        return jsonify({
            "filename": filename,
            "project": project,
            "tasks_count": len(tasks),
            "tasks": tasks[:20]  # 返回前20条用于预览
        })
    else:
        return jsonify({"error": "只支持.xlsx文件"}), 400


@app.route('/api/excel/files', methods=['GET'])
def list_excel_files():
    """列出已上传的Excel文件"""
    files = []
    if os.path.exists(app.config['UPLOAD_FOLDER']):
        for root, dirs, filenames in os.walk(app.config['UPLOAD_FOLDER']):
            for filename in filenames:
                if filename.endswith('.xlsx'):
                    full_path = os.path.join(root, filename)
                    files.append({
                        "name": filename,
                        "path": full_path,
                        "relative_path": os.path.relpath(full_path, app.config['UPLOAD_FOLDER']),
                        "size": os.path.getsize(full_path),
                        "modified": datetime.fromtimestamp(os.path.getmtime(full_path)).strftime('%Y-%m-%d %H:%M')
                    })
    return jsonify(files)


@app.route('/api/excel/parse/<filename>', methods=['GET'])
def parse_excel_file(filename):
    """解析Excel文件并返回任务列表"""
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "文件不存在"}), 404

    tasks = parse_excel_tasks(file_path)
    return jsonify({
        "filename": filename,
        "total_tasks": len(tasks),
        "tasks": tasks
    })


# ==================== Git项目配置API ====================

@app.route('/api/git-projects', methods=['GET'])
def get_git_projects():
    """获取Git项目列表"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM git_projects ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()

    projects = []
    for row in rows:
        project = dict(row)
        # 检查路径是否存在
        project['exists'] = os.path.exists(project['path'])
        projects.append(project)

    return jsonify(projects)


@app.route('/api/git-projects/validate-path', methods=['POST'])
def validate_git_path():
    """验证Git仓库路径是否有效"""
    data = request.json
    path = data.get('path', '')

    if not path:
        return jsonify({"valid": False, "error": "路径不能为空"})

    # 检查路径是否存在
    if not os.path.exists(path):
        return jsonify({"valid": False, "error": "路径不存在"})

    # 检查是否是目录
    if not os.path.isdir(path):
        return jsonify({"valid": False, "error": "路径不是目录"})

    # 检查是否是Git仓库（存在.git目录）
    git_dir = os.path.join(path, '.git')
    if not os.path.exists(git_dir):
        return jsonify({"valid": False, "error": "不是有效的Git仓库（未找到.git目录）"})

    # 尝试获取Git信息
    try:
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        if result.returncode == 0:
            repo_name = os.path.basename(result.stdout.strip())
            return jsonify({
                "valid": True,
                "repo_name": repo_name,
                "path": path,
                "message": "有效Git仓库"
            })
        else:
            return jsonify({"valid": False, "error": "无法读取Git信息"})
    except Exception as e:
        return jsonify({"valid": False, "error": str(e)})


@app.route('/api/git-projects', methods=['POST'])
def create_git_project():
    """添加Git项目"""
    data = request.json
    name = data.get('name')
    path = data.get('path')

    if not name or not path:
        return jsonify({"error": "项目名称和路径不能为空"}), 400

    if not os.path.exists(path):
        return jsonify({"error": "路径不存在"}), 400

    # 验证是否是Git仓库
    git_dir = os.path.join(path, '.git')
    if not os.path.exists(git_dir):
        return jsonify({"error": "不是有效的Git仓库"}), 400

    conn = get_db()
    cursor = conn.cursor()

    # 检查是否已存在
    cursor.execute('SELECT id FROM git_projects WHERE path=?', (path,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"error": "该项目已添加"}), 400

    cursor.execute(
        'INSERT INTO git_projects (name, path) VALUES (?, ?)',
        (name, path)
    )
    conn.commit()
    project_id = cursor.lastrowid
    conn.close()

    return jsonify({"id": project_id, "name": name, "path": path}), 201


@app.route('/api/git-projects/<int:project_id>', methods=['DELETE'])
def delete_git_project(project_id):
    """删除Git项目"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM git_projects WHERE id=?', (project_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


@app.route('/api/git-projects/<int:project_id>/authors', methods=['GET'])
def get_git_project_authors(project_id):
    """获取项目的Git提交作者列表"""
    since = request.args.get('since')
    until = request.args.get('until')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT path FROM git_projects WHERE id=?', (project_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "项目不存在"}), 404

    project_path = row['path']
    authors = parse_git_authors(project_path, since, until)

    return jsonify({
        "project_id": project_id,
        "authors_count": len(authors),
        "authors": authors
    })


@app.route('/api/git-projects/<int:project_id>/commits', methods=['GET'])
def get_git_project_commits(project_id):
    """获取项目的Git提交记录"""
    since = request.args.get('since')
    until = request.args.get('until')
    author = request.args.get('author')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT path FROM git_projects WHERE id=?', (project_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "项目不存在"}), 404

    project_path = row['path']
    commits = get_git_commits(project_path, since, until)

    # 按作者过滤
    if author:
        commits = [c for c in commits if c['author'] == author]

    return jsonify({
        "project_id": project_id,
        "commits_count": len(commits),
        "commits": commits
    })


# ==================== 团队成员管理API ====================

@app.route('/api/team-members', methods=['GET'])
def get_team_members():
    """获取团队成员列表"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM team_members ORDER BY name')
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route('/api/team-members', methods=['POST'])
def create_team_member():
    """添加团队成员"""
    data = request.json
    name = data.get('name')
    email = data.get('email')
    git_name = data.get('git_name', '')
    role = data.get('role', 'developer')

    if not name or not email:
        return jsonify({"error": "姓名和邮箱不能为空"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO team_members (name, email, git_name, role) VALUES (?, ?, ?, ?)',
        (name, email, git_name, role)
    )
    conn.commit()
    member_id = cursor.lastrowid
    conn.close()

    return jsonify({"id": member_id, "name": name, "email": email}), 201


@app.route('/api/team-members/<int:member_id>', methods=['PUT'])
def update_team_member(member_id):
    """更新团队成员"""
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE team_members SET name=?, email=?, git_name=?, role=? WHERE id=?',
        (data.get('name'), data.get('email'), data.get('git_name'), data.get('role'), member_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})


@app.route('/api/team-members/<int:member_id>', methods=['DELETE'])
def delete_team_member(member_id):
    """删除团队成员"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM team_members WHERE id=?', (member_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


@app.route('/api/team-members/import', methods=['POST'])
def import_team_members():
    """从Git项目导入团队成员"""
    data = request.json
    project_id = data.get('project_id')
    since = data.get('since')
    until = data.get('until')

    if not project_id:
        return jsonify({"error": "项目ID不能为空"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT path FROM git_projects WHERE id=?', (project_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "项目不存在"}), 404

    authors = parse_git_authors(row['path'], since, until)

    # 添加到团队成员表
    conn = get_db()
    cursor = conn.cursor()
    added_count = 0

    for author in authors:
        # 检查是否已存在
        cursor.execute('SELECT id FROM team_members WHERE email=?', (author['email'],))
        if not cursor.fetchone():
            cursor.execute(
                'INSERT INTO team_members (name, email, git_name, role) VALUES (?, ?, ?, ?)',
                (author['name'], author['email'], author['git_name'], 'developer')
            )
            added_count += 1

    conn.commit()
    conn.close()

    return jsonify({
        "imported_count": added_count,
        "total_authors": len(authors),
        "authors": authors
    })


# ==================== 报告生成API ====================

def load_prompt_file(filepath: str) -> str:
    """加载Prompt文件"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except:
        return ""


@app.route('/api/reports/generate', methods=['POST'])
def generate_report():
    """生成进度报告"""
    data = request.json
    task_type = data.get('task_type', 'daily')  # daily or weekly
    time_range = data.get('time_range', '2days')  # 1day, 2days, 1week
    selected_projects = data.get('projects', [])
    selected_members = data.get('members', [])
    report_mode = data.get('mode', 'manual')  # manual or scheduled

    # 计算时间范围
    now = datetime.now()
    if time_range == '1day':
        since = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        until = now.strftime("%Y-%m-%d")
        date_desc = "最近1天"
    elif time_range == '1week':
        since = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        until = now.strftime("%Y-%m-%d")
        date_desc = "最近1周"
    else:  # 2days
        since = (now - timedelta(days=2)).strftime("%Y-%m-%d")
        until = now.strftime("%Y-%m-%d")
        date_desc = "最近2天"

    # 获取Git项目
    conn = get_db()
    cursor = conn.cursor()

    if selected_projects:
        cursor.execute(f'SELECT * FROM git_projects WHERE id IN ({",".join(["?"] * len(selected_projects))})', selected_projects)
    else:
        cursor.execute('SELECT * FROM git_projects')
    git_projects = cursor.fetchall()

    if selected_members:
        cursor.execute(f'SELECT * FROM team_members WHERE id IN ({",".join(["?"] * len(selected_members))})', selected_members)
    else:
        cursor.execute('SELECT * FROM team_members')
    members = cursor.fetchall()
    conn.close()

    if not git_projects:
        return jsonify({"error": "请至少选择一个Git项目"}), 400

    # 生成报告上下文
    context_parts = []
    context_parts.append(f"日期范围: {date_desc} ({since} ~ {until})")
    context_parts.append("")

    # 收集每个项目的提交和作者
    all_authors = {}
    all_commits = []

    for project in git_projects:
        project_path = project['path']
        if not os.path.exists(project_path):
            continue

        context_parts.append(f"## 项目: {project['name']}")
        context_parts.append(f"路径: {project_path}")
        context_parts.append("")

        # 获取该项目的作者
        authors = parse_git_authors(project_path, since, until)
        for author in authors:
            key = f"{author['name']}|{author['email']}"
            if key not in all_authors:
                all_authors[key] = author

        # 获取提交记录
        commits = get_git_commits(project_path, since, until)
        all_commits.extend(commits)

        context_parts.append(f"### Git提交记录 (共 {len(commits)} 条)")
        for commit in commits[:50]:  # 最多显示50条
            context_parts.append(f"- [{commit['hash']}] {commit['message']} ({commit['author']}, {commit['date']})")
        context_parts.append("")

    # 人员列表
    context_parts.append("## 参与人员")
    for key, author in all_authors.items():
        context_parts.append(f"- {author['name']} <{author['email']}> (Git: {author['git_name']})")
    context_parts.append("")

    # 保存报告
    date_str = now.strftime("%Y-%m-%d")
    year_month = now.strftime("%Y%m")
    output_dir = os.path.join(app_config.OUTPUT_DIR, year_month, "by_project", task_type)
    os.makedirs(output_dir, exist_ok=True)

    report_content = "\n".join(context_parts)
    report_filename = f"进度报告_{date_str}_{date_desc}.md"
    report_path = os.path.join(output_dir, report_filename)

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    # 记录日志
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO report_logs (task_type, time_range, report_path, status) VALUES (?, ?, ?, ?)',
        (task_type, date_desc, report_path, 'completed')
    )
    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "report_path": report_path,
        "report_filename": report_filename,
        "date_range": date_desc,
        "projects_count": len(git_projects),
        "authors_count": len(all_authors),
        "commits_count": len(all_commits),
        "members_count": len(members) if members else len(all_authors)
    })


@app.route('/api/reports/preview', methods=['POST'])
def preview_report():
    """预览报告内容（不生成文件）"""
    data = request.json
    time_range = data.get('time_range', '2days')
    selected_projects = data.get('projects', [])

    # 计算时间范围
    now = datetime.now()
    if time_range == '1day':
        since = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        until = now.strftime("%Y-%m-%d")
        date_desc = "最近1天"
    elif time_range == '1week':
        since = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        until = now.strftime("%Y-%m-%d")
        date_desc = "最近1周"
    else:
        since = (now - timedelta(days=2)).strftime("%Y-%m-%d")
        until = now.strftime("%Y-%m-%d")
        date_desc = "最近2天"

    conn = get_db()
    cursor = conn.cursor()

    if selected_projects:
        cursor.execute(f'SELECT * FROM git_projects WHERE id IN ({",".join(["?"] * len(selected_projects))})', selected_projects)
    else:
        cursor.execute('SELECT * FROM git_projects')
    git_projects = cursor.fetchall()
    conn.close()

    # 收集作者信息
    all_authors = []
    for project in git_projects:
        authors = parse_git_authors(project['path'], since, until)
        for author in authors:
            if author not in all_authors:
                all_authors.append(author)

    return jsonify({
        "date_range": date_desc,
        "since": since,
        "until": until,
        "projects_count": len(git_projects),
        "authors": all_authors,
        "authors_count": len(all_authors)
    })


@app.route('/api/reports/logs', methods=['GET'])
def get_report_logs():
    """获取报告生成记录"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM report_logs ORDER BY generated_at DESC LIMIT 50')
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


# ==================== LLM配置API ====================

@app.route('/api/llm/config', methods=['GET'])
def get_llm_config():
    """获取LLM配置"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM llm_config WHERE is_active=1 ORDER BY id DESC LIMIT 1')
    row = cursor.fetchone()
    conn.close()

    if row:
        config = dict(row)
        # 不要返回完整的API key
        if config.get('api_key'):
            config['api_key'] = mask_api_key(config['api_key'])
        return jsonify(config)
    else:
        # 返回默认配置
        return jsonify({
            "provider": "minimax",
            "api_key": "",
            "base_url": "https://api.minimaxi.com/anthropic",
            "model_name": "MiniMax-M2.7",
            "max_tokens": 10000,
            "temperature": 0.5
        })


@app.route('/api/llm/config', methods=['POST'])
def save_llm_config():
    """保存LLM配置"""
    data = request.json

    provider = data.get('provider', 'minimax')
    api_key = data.get('api_key', '')
    base_url = data.get('base_url', 'https://api.minimaxi.com/anthropic')
    model_name = data.get('model_name', 'MiniMax-M2.7')
    max_tokens = data.get('max_tokens', 10000)
    temperature = data.get('temperature', 0.5)

    conn = get_db()
    cursor = conn.cursor()

    # 先禁用所有现有配置
    cursor.execute('UPDATE llm_config SET is_active=0')

    # 插入新配置
    cursor.execute('''
        INSERT INTO llm_config (provider, api_key, base_url, model_name, max_tokens, temperature, is_active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    ''', (provider, api_key, base_url, model_name, max_tokens, temperature))

    conn.commit()
    conn.close()

    return jsonify({"status": "success", "message": "LLM配置已保存"})


@app.route('/api/llm/providers', methods=['GET'])
def get_llm_providers():
    """获取支持的LLM提供商列表"""
    providers = [
        {"id": "minimax", "name": "MiniMax", "default_url": "https://api.minimaxi.com/anthropic"},
        {"id": "openai", "name": "OpenAI", "default_url": "https://api.openai.com/v1"},
        {"id": "anthropic", "name": "Anthropic", "default_url": "https://api.anthropic.com"},
        {"id": "azure", "name": "Azure OpenAI", "default_url": "https://YOUR_RESOURCE.openai.azure.com"},
        {"id": "custom", "name": "自定义", "default_url": ""}
    ]
    return jsonify(providers)


def mask_api_key(key: str) -> str:
    """脱敏API key"""
    if not key or len(key) < 8:
        return "***"
    return key[:4] + "***" + key[-4:] if len(key) > 8 else "***"


@app.route('/api/llm/test', methods=['POST'])
def test_llm_connection():
    """测试LLM连接"""
    data = request.json

    provider = data.get('provider', 'minimax')
    api_key = data.get('api_key', '')
    base_url = data.get('base_url', '')
    model_name = data.get('model_name', 'MiniMax-M2.7')

    if not api_key:
        return jsonify({"success": False, "error": "API Key不能为空"})

    try:
        import anthropic

        client = anthropic.Anthropic(
            base_url=base_url if base_url else None,
            api_key=api_key
        )

        response = client.messages.create(
            model=model_name,
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}]
        )

        return jsonify({
            "success": True,
            "message": "连接成功",
            "response": str(response.content[0].text)[:100]
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })


# ==================== 定时任务管理API ====================

@app.route('/api/scheduled-tasks', methods=['GET'])
def get_scheduled_tasks():
    """获取定时任务列表"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM scheduled_tasks WHERE is_active=1 ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route('/api/scheduled-tasks', methods=['POST'])
def create_scheduled_task():
    """创建定时任务"""
    data = request.json
    name = data.get('name')
    task_type = data.get('task_type', 'daily')
    schedule = data.get('schedule', '0 9 * * *')  # 默认每天早上9点
    projects = json.dumps(data.get('projects', []))
    time_range = data.get('time_range', '2days')
    recipients = json.dumps(data.get('recipients', []))

    if not name:
        return jsonify({"error": "任务名称不能为空"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO scheduled_tasks (name, task_type, schedule, projects, time_range, recipients) VALUES (?, ?, ?, ?, ?, ?)',
        (name, task_type, schedule, projects, time_range, recipients)
    )
    conn.commit()
    task_id = cursor.lastrowid
    conn.close()

    return jsonify({"id": task_id, "name": name}), 201


@app.route('/api/scheduled-tasks/<int:task_id>', methods=['DELETE'])
def delete_scheduled_task(task_id):
    """删除定时任务"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE scheduled_tasks SET is_active=0 WHERE id=?', (task_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


# ==================== 智能体实时推送 (SSE) ====================

# 存储SSE客户端
sse_clients = {}


@app.route('/api/events/<int:developer_id>')
def sse_events(developer_id):
    """SSE端点，用于推送智能体分析结果"""
    def generate():
        import time
        client_id = developer_id
        sse_clients[client_id] = True

        try:
            while sse_clients.get(client_id, False):
                # 每30秒发送一次心跳
                heartbeat = f"data: {{'type':'heartbeat','time':'{datetime.now().isoformat()}'}}\n\n"
                yield heartbeat

                # 检查新消息
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT * FROM pm_messages
                        WHERE receiver_id = ? AND is_read = 0
                        ORDER BY created_at DESC LIMIT 5
                    ''', (developer_id,))
                    messages = [dict(row) for row in cursor.fetchall()]

                if messages:
                    msg_data = json.dumps(messages, ensure_ascii=False)
                    msg_event = f"data: {{'type':'messages','count':{len(messages)},'data':{msg_data}}}\n\n"
                    yield msg_event

                time.sleep(30)
        except GeneratorExit:
            pass
        finally:
            sse_clients.pop(client_id, None)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )


@app.route('/api/events/stop/<int:developer_id>', methods=['POST'])
def stop_sse(developer_id):
    """停止SSE连接"""
    sse_clients.pop(developer_id, None)
    return jsonify({'status': 'stopped'})


# ==================== 前端路由 ====================

@app.route('/')
def index():
    """返回前端页面"""
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/dashboard')
def dashboard():
    """返回开发者仪表盘"""
    return send_from_directory(app.static_folder, 'index_new.html')


@app.route('/new')
def new_index():
    """新版仪表盘入口"""
    return send_from_directory(app.static_folder, 'index_new.html')


@app.route('/<path:path>')
def serve_static(path):
    """静态文件服务"""
    return send_from_directory(app.static_folder, path)


# ==================== 初始化 ====================

if __name__ == '__main__':
    init_db()
    print("=" * 60)
    print("工作汇报系统已启动")
    print("请访问 http://localhost:5000")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)