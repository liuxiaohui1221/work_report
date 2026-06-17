#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能体系统框架 - 多智能体协作实现项目进度管理

包含：
1. Agent基类 - 所有智能体的父类
2. ProjectManagerAgent - 项目经理智能体（协调者）
3. ProgressTrackerAgent - 进度追踪智能体
4. TestExpertAgent - 测试专家智能体
5. ArchitectAgent - 架构师智能体
"""

import os
import json
import subprocess
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from abc import ABC, abstractmethod
from main.models import (
    get_db_connection, ProjectDAO, DeveloperDAO, TaskDAO, TaskService,
    MessageDAO, BugDAO
)


# ========== LLM调用 ==========

def call_llm(prompt: str, system: str = None, model: str = None) -> str:
    """调用配置的LLM"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM llm_config WHERE is_active=1 ORDER BY id DESC LIMIT 1')
        row = cursor.fetchone()

    if not row:
        return "LLM未配置"

    config = dict(row)
    api_key = config.get('api_key', '')
    base_url = config.get('base_url', 'https://api.minimaxi.com/anthropic')
    model = model or config.get('model_name', 'MiniMax-M3')
    temperature = config.get('temperature', 0.3)  # 降低温度以保持一致性

    if not api_key:
        return "LLM API Key未配置"

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
            max_tokens=8000,
            temperature=temperature,
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


# ========== Agent基类 ==========

class BaseAgent(ABC):
    """智能体基类"""

    def __init__(self, name: str, role: str, description: str = ""):
        self.name = name
        self.role = role
        self.description = description
        self.created_at = datetime.now()

    @abstractmethod
    def execute(self, context: Dict) -> Dict:
        """执行智能体任务"""
        pass

    def log_action(self, action: str, result: str, details: str = ""):
        """记录智能体执行日志"""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO pm_agent_logs (agent_type, action, result, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (self.role, action, result))
            conn.commit()

    def send_message(self, receiver_id: int, title: str, content: str,
                      msg_type: str = 'system', related_task_id: int = None) -> int:
        """发送消息给指定开发人员"""
        return MessageDAO.create(
            msg_type=msg_type,
            title=title,
            content=content,
            sender_id=None,  # 系统发送
            receiver_id=receiver_id,
            related_task_id=related_task_id
        )

    def get_project_context(self, project_id: int) -> Dict:
        """获取项目上下文"""
        project = ProjectDAO.get_by_id(project_id)
        if not project:
            return {}

        developers = DeveloperDAO.get_by_project(project_id)
        tasks = TaskDAO.get_by_project(project_id)

        return {
            'project': project,
            'developers': developers,
            'tasks': tasks,
            'task_count': len(tasks),
            'completed_count': sum(1 for t in tasks if t.get('status') == '已完成'),
            'in_progress_count': sum(1 for t in tasks if t.get('status') == '开发中'),
            'blocked_count': sum(1 for t in tasks if t.get('status') == '被阻塞')
        }


# ========== 进度追踪智能体 ==========

class ProgressTrackerAgent(BaseAgent):
    """进度追踪智能体 - 监控Git提交，自动更新任务进度"""

    def __init__(self):
        super().__init__("进度追踪助手", "progress_tracker",
                        "负责跟踪项目进度，识别风险，汇报状态")

    def execute(self, context: Dict) -> Dict:
        """执行进度追踪"""
        project_id = context.get('project_id')
        if not project_id:
            return {'error': '缺少项目ID'}

        # 获取项目信息
        project = ProjectDAO.get_by_id(project_id)
        if not project or not project.get('repo_path'):
            return {'error': '项目未配置Git路径'}

        repo_path = project['repo_path']
        if not os.path.exists(repo_path):
            return {'error': f'项目路径不存在: {repo_path}'}

        results = []

        # 1. 分析Git提交
        commit_analysis = self._analyze_git_commits(repo_path, days=1)
        results.append(commit_analysis)

        # 2. 更新任务状态（基于提交）
        task_updates = self._update_tasks_from_commits(project_id, commit_analysis)
        results.append(task_updates)

        # 3. 检测阻塞任务
        blockers = self._report_blockers(project_id)
        results.append(blockers)

        # 4. 生成进度报告
        report = self._generate_progress_report(project_id, results)

        self.log_action('execute', 'completed',
                        f"项目{project_id}进度追踪完成，{commit_analysis.get('commit_count', 0)}条提交")

        return {
            'success': True,
            'project_id': project_id,
            'results': results,
            'report': report
        }

    def _analyze_git_commits(self, repo_path: str, days: int = 1) -> Dict:
        """分析Git提交记录"""
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "log", "--since=" + since,
                 "--pretty=format:%H|%s|%an|%ad", "--date=short"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=30
            )

            if result.returncode != 0:
                return {'error': 'Git命令执行失败', 'details': result.stderr}

            lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
            commits = []
            authors = {}

            for line in lines:
                parts = line.split("|", 3)
                if len(parts) >= 4:
                    commit = {
                        'hash': parts[0][:12],
                        'message': parts[1],
                        'author': parts[2],
                        'date': parts[3]
                    }
                    commits.append(commit)

                    author = parts[2]
                    if author not in authors:
                        authors[author] = {'name': author, 'count': 0, 'commits': []}
                    authors[author]['count'] += 1
                    authors[author]['commits'].append(commit)

            return {
                'commit_count': len(commits),
                'authors': list(authors.values()),
                'commits': commits[:20],  # 只保留最近20条
                'date_range': f"最近{days}天"
            }

        except Exception as e:
            return {'error': str(e)}

    def _update_tasks_from_commits(self, project_id: int, commit_analysis: Dict) -> Dict:
        """根据提交记录更新任务"""
        if 'error' in commit_analysis:
            return commit_analysis

        updated_tasks = []
        commits = commit_analysis.get('commits', [])

        for commit in commits:
            message = commit.get('message', '')

            # 查找是否有匹配的任务（通过commit消息关联）
            tasks = TaskDAO.get_by_project(project_id)
            for task in tasks:
                task_title = task.get('title', '')
                # 如果提交消息包含任务标题的关键字
                if task_title and len(task_title) > 5 and task_title[:10] in message:
                    # 检查任务是否还在进行中
                    if task.get('status') in ['开发中', '待联调']:
                        # 自动更新进度（这里简化处理，实际可能需要更复杂的匹配）
                        pass

        return {
            'updated_count': len(updated_tasks),
            'updated_tasks': updated_tasks
        }

    def _report_blockers(self, project_id: int) -> Dict:
        """报告阻塞任务"""
        blocked_tasks = TaskDAO.get_blocked_tasks(project_id)

        if not blocked_tasks:
            return {'blocked_count': 0, 'tasks': []}

        # 为每个阻塞任务的通知负责人
        notifications = []
        for task in blocked_tasks:
            assignee_id = task.get('assignee_id')
            if assignee_id:
                # 发送提醒
                message = f"""🚧 您的任务被阻塞

任务：{task['title']}
阻塞原因：前置任务未完成
建议：联系 {task.get('blocked_by_name', '负责人')} 尽快完成前置任务
"""
                self.send_message(
                    receiver_id=assignee_id,
                    title='任务被阻塞提醒',
                    content=message,
                    msg_type='warning',
                    related_task_id=task['id']
                )
                notifications.append(task['id'])

        return {
            'blocked_count': len(blocked_tasks),
            'blocked_tasks': blocked_tasks,
            'notifications_sent': len(notifications)
        }

    def _generate_progress_report(self, project_id: int, results: List[Dict]) -> str:
        """生成进度报告"""
        context = self.get_project_context(project_id)
        project = context.get('project', {})

        report = f"""📊 项目进度报告 - {project.get('name', '未知项目')}

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 概览
- 总任务数：{context['task_count']}
- 进行中：{context['in_progress_count']}
- 被阻塞：{context['blocked_count']}
- 已完成：{context['completed_count']}
- 完成率：{round(context['completed_count']/context['task_count']*100, 1) if context['task_count'] > 0 else 0}%

## 今日提交
"""

        for r in results:
            if 'commit_count' in r:
                report += f"- 提交数：{r['commit_count']}\n"
                if r.get('authors'):
                    report += "- 参与者：\n"
                    for author in r['authors'][:5]:
                        report += f"  - {author['name']}: {author['count']}次提交\n"

        return report


# ========== 测试专家智能体 ==========

class TestExpertAgent(BaseAgent):
    """测试专家智能体 - 分析代码变更，发现Bug"""

    def __init__(self):
        super().__init__("测试专家", "test_expert",
                        "负责分析代码变更，发现Bug，主动汇报")

    def execute(self, context: Dict) -> Dict:
        """执行测试分析"""
        project_id = context.get('project_id')
        if not project_id:
            return {'error': '缺少项目ID'}

        project = ProjectDAO.get_by_id(project_id)
        if not project or not project.get('repo_path'):
            return {'error': '项目未配置Git路径'}

        repo_path = project['repo_path']
        days = context.get('days', 1)

        results = []

        # 1. 获取代码变更
        changes = self._get_code_changes(repo_path, days)
        results.append(changes)

        # 2. 分析潜在Bug
        bugs = self._analyze_potential_bugs(changes, project_id)
        results.append(bugs)

        # 3. 生成测试报告
        report = self._generate_test_report(project_id, results)

        self.log_action('execute', 'completed',
                        f"项目{project_id}测试分析完成，发现{len(bugs.get('potential_bugs', []))}个潜在问题")

        return {
            'success': True,
            'project_id': project_id,
            'results': results,
            'report': report
        }

    def _get_code_changes(self, repo_path: str, days: int = 1) -> Dict:
        """获取代码变更"""
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        try:
            # 获取变更的文件
            result = subprocess.run(
                ["git", "-C", repo_path, "diff", "--name-only",
                 f"--since={since}", "--no-merges"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=30
            )

            if result.returncode != 0:
                return {'error': 'Git命令执行失败', 'details': result.stderr}

            changed_files = [f for f in result.stdout.strip().split('\n') if f]

            # 获取每个文件的变更统计
            file_changes = []
            for file in changed_files[:20]:  # 限制分析前20个文件
                diff_result = subprocess.run(
                    ["git", "-C", repo_path, "diff", "--stat", file,
                     f"--since={since}"],
                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                    timeout=10
                )

                file_changes.append({
                    'file': file,
                    'stats': diff_result.stdout.strip()
                })

            return {
                'changed_files_count': len(changed_files),
                'changed_files': changed_files,
                'file_changes': file_changes
            }

        except Exception as e:
            return {'error': str(e)}

    def _analyze_potential_bugs(self, changes: Dict, project_id: int) -> Dict:
        """分析潜在Bug"""
        if 'error' in changes:
            return changes

        potential_bugs = []

        # 分析代码模式（简化版，实际需要更复杂的分析）
        for file in changes.get('changed_files', []):
            # 检查是否有常见的bug模式
            file_path = os.path.join(
                ProjectDAO.get_by_id(project_id).get('repo_path', ''),
                file
            )

            if not os.path.exists(file_path):
                continue

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                    # 检查常见问题模式
                    issues = []

                    # 1. 缺少空值检查
                    if re.search(r'\.(len|size|count|get|substr|slice)\(', content):
                        if not re.search(r'if\s*.*\s*==\s*null|if\s*.*\.get\(|if\s*!', content):
                            issues.append('可能缺少空值检查')

                    # 2. 未捕获的异常
                    if 'try' not in content and 'catch' not in content:
                        if any(kw in content for kw in ['function', 'def ', 'async']):
                            issues.append('可能缺少异常处理')

                    # 3. 硬编码敏感信息
                    if re.search(r'password\s*=|api[_-]?key\s*=|secret\s*=', content, re.I):
                        issues.append('可能存在硬编码敏感信息')

                    if issues:
                        potential_bugs.append({
                            'file': file,
                            'issues': issues
                        })

            except Exception:
                pass

        return {
            'potential_bugs': potential_bugs,
            'bug_count': len(potential_bugs)
        }

    def _generate_test_report(self, project_id: int, results: List[Dict]) -> str:
        """生成测试报告"""
        context = self.get_project_context(project_id)
        project = context.get('project', {})

        report = f"""🐛 测试专家报告 - {project.get('name', '未知项目')}

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 代码变更分析
"""

        for r in results:
            if 'changed_files_count' in r:
                report += f"- 变更文件数：{r['changed_files_count']}\n"

            if 'potential_bugs' in r:
                bugs = r['potential_bugs']
                report += f"- 潜在问题：{len(bugs)}个\n"
                if bugs:
                    report += "\n### 发现的问题：\n"
                    for bug in bugs[:10]:
                        report += f"\n📄 {bug['file']}\n"
                        for issue in bug['issues']:
                            report += f"  ⚠️ {issue}\n"

        return report


# ========== 项目经理智能体 ==========

class ProjectManagerAgent(BaseAgent):
    """项目经理智能体 - 协调其他智能体，汇总进度，决策"""

    def __init__(self):
        super().__init__("项目经理", "project_manager",
                        "负责协调各专家智能体，完成项目整体管理和决策")
        self.progress_tracker = ProgressTrackerAgent()
        self.test_expert = TestExpertAgent()

    def execute(self, context: Dict) -> Dict:
        """执行项目管理"""
        project_id = context.get('project_id')
        if not project_id:
            return {'error': '缺少项目ID'}

        action = context.get('action', 'daily_report')

        if action == 'daily_report':
            return self._generate_daily_report(project_id)
        elif action == 'risk_analysis':
            return self._analyze_risks(project_id)
        elif action == 'coordinate':
            return self._coordinate_agents(project_id)
        else:
            return {'error': f'未知操作: {action}'}

    def _generate_daily_report(self, project_id: int) -> Dict:
        """生成日报"""
        project = ProjectDAO.get_by_id(project_id)
        if not project:
            return {'error': '项目不存在'}

        # 1. 收集进度信息
        progress_result = self.progress_tracker.execute({'project_id': project_id})

        # 2. 收集测试信息
        test_result = self.test_expert.execute({'project_id': project_id})

        # 3. 汇总数据
        context = self.get_project_context(project_id)
        developers = context.get('developers', [])
        tasks = context.get('tasks', [])

        # 4. 生成AI报告
        report_prompt = f"""请为项目 '{project['name']}' 生成一份日报，包含：

1. 今日进度总结
2. 完成任务列表
3. 进行中任务
4. 风险和阻塞点
5. 明日计划建议

当前数据：
- 总任务：{len(tasks)}
- 进行中：{context['in_progress_count']}
- 已完成：{context['completed_count']}
- 被阻塞：{context['blocked_count']}

请用清晰的格式输出，适合发送给团队。
"""

        ai_report = call_llm(report_prompt, system="你是一个专业的项目经理，擅长生成简洁明了的项目报告。")

        report = f"""📋 项目日报 - {project['name']}

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

{ai_report}

---
🤖 此报告由AI自动生成
"""

        self.log_action('daily_report', 'completed',
                        f"生成项目{project_id}日报")

        return {
            'success': True,
            'project_id': project_id,
            'report': report,
            'stats': {
                'total_tasks': context['task_count'],
                'in_progress': context['in_progress_count'],
                'completed': context['completed_count'],
                'blocked': context['blocked_count']
            }
        }

    def _analyze_risks(self, project_id: int) -> Dict:
        """分析项目风险"""
        context = self.get_project_context(project_id)
        tasks = context.get('tasks', [])

        risks = []

        # 1. 检查被阻塞的任务
        blocked_tasks = [t for t in tasks if t.get('status') == '被阻塞']
        if blocked_tasks:
            risks.append({
                'type': 'blocked_tasks',
                'severity': 'high',
                'count': len(blocked_tasks),
                'description': f'{len(blocked_tasks)}个任务被阻塞',
                'tasks': blocked_tasks[:5]
            })

        # 2. 检查超期任务
        now = datetime.now().date()
        overdue_tasks = []
        for task in tasks:
            due_date = task.get('due_date')
            if due_date and task.get('status') != '已完成':
                try:
                    due = datetime.strptime(str(due_date), '%Y-%m-%d').date()
                    if due < now:
                        overdue_tasks.append(task)
                except:
                    pass

        if overdue_tasks:
            risks.append({
                'type': 'overdue',
                'severity': 'high',
                'count': len(overdue_tasks),
                'description': f'{len(overdue_tasks)}个任务已超期',
                'tasks': overdue_tasks[:5]
            })

        # 3. 检查长时间未动的任务（3天以上）
        stale_tasks = []
        for task in tasks:
            if task.get('status') == '开发中':
                updated = task.get('updated_at', '')
                if updated:
                    try:
                        upd_time = datetime.strptime(updated[:10], '%Y-%m-%d')
                        if (datetime.now() - upd_time).days > 3:
                            stale_tasks.append(task)
                    except:
                        pass

        if stale_tasks:
            risks.append({
                'type': 'stale',
                'severity': 'medium',
                'count': len(stale_tasks),
                'description': f'{len(stale_tasks)}个任务超过3天未更新',
                'tasks': stale_tasks[:5]
            })

        # 4. AI风险分析
        risks_prompt = f"""分析以下项目风险：

风险概览：
- 阻塞任务：{len(blocked_tasks)}个
- 超期任务：{len(overdue_tasks)}个
- 停滞任务：{len(stale_tasks)}个

给出：
1. 最重要的3个风险点
2. 建议的解决优先级
3. 具体行动建议
"""

        ai_analysis = call_llm(risks_prompt, system="你是一个经验丰富的项目经理，擅长风险管理和解决方案。")

        return {
            'success': True,
            'project_id': project_id,
            'risks': risks,
            'analysis': ai_analysis
        }

    def _coordinate_agents(self, project_id: int) -> Dict:
        """协调各智能体工作"""
        results = {}

        # 并行执行各智能体
        results['progress'] = self.progress_tracker.execute({'project_id': project_id})
        results['test'] = self.test_expert.execute({'project_id': project_id})

        # 汇总结果
        summary = self._summarize_results(results)

        return {
            'success': True,
            'project_id': project_id,
            'results': results,
            'summary': summary
        }

    def _summarize_results(self, results: Dict) -> str:
        """汇总各智能体结果"""
        summary = "## 智能体协调报告\n\n"

        for agent_name, result in results.items():
            if 'error' in result:
                summary += f"- {agent_name}: ❌ {result['error']}\n"
            else:
                summary += f"- {agent_name}: ✅ 完成\n"

        return summary


# ========== 架构师智能体 ==========

class ArchitectAgent(BaseAgent):
    """架构师智能体 - 系统架构设计和技术选型"""

    def __init__(self):
        super().__init__("架构师", "architect",
                        "负责系统架构设计、技术选型和代码审查")

    def execute(self, context: Dict) -> Dict:
        """执行架构相关任务"""
        action = context.get('action', 'review')

        if action == 'review':
            return self._review_code(context)
        elif action == 'suggest':
            return self._suggest_architecture(context)
        else:
            return {'error': f'未知操作: {action}'}

    def _review_code(self, context: Dict) -> Dict:
        """代码审查"""
        project_id = context.get('project_id')
        file_path = context.get('file_path')

        if not project_id:
            return {'error': '缺少项目ID'}

        project = ProjectDAO.get_by_id(project_id)
        if not project or not project.get('repo_path'):
            return {'error': '项目未配置Git路径'}

        repo_path = project['repo_path']

        if file_path:
            full_path = os.path.join(repo_path, file_path)
            if os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    code = f.read()

                review_prompt = f"""请审查以下代码，提供：
1. 代码质量评估（1-10分）
2. 优点
3. 问题和建议
4. 安全风险
5. 性能优化建议

代码文件：{file_path}

```{code[:3000]}```
"""

                review = call_llm(review_prompt, system="你是一个经验丰富的架构师和代码审查专家。")

                return {
                    'success': True,
                    'file': file_path,
                    'review': review
                }

        return {'error': '缺少文件路径'}

    def _suggest_architecture(self, context: Dict) -> Dict:
        """建议架构"""
        project_id = context.get('project_id')
        requirements = context.get('requirements', '')

        if not requirements:
            return {'error': '缺少需求描述'}

        project = ProjectDAO.get_by_id(project_id)
        project_info = f"项目名称：{project['name']}\n" if project else ""

        prompt = f"""{project_info}
需求：{requirements}

请提供：
1. 推荐的架构方案
2. 技术栈选型
3. 模块划分建议
4. 关键技术决策
5. 潜在挑战和应对方案
"""

        suggestion = call_llm(prompt, system="你是一个经验丰富的系统架构师，擅长设计可扩展、高性能的系統架构。")

        return {
            'success': True,
            'suggestion': suggestion
        }


# ========== 智能体调度器 ==========

class AgentScheduler:
    """智能体调度器 - 定时执行各智能体任务"""

    def __init__(self):
        self.agents = {
            'project_manager': ProjectManagerAgent(),
            'progress_tracker': ProgressTrackerAgent(),
            'test_expert': TestExpertAgent(),
            'architect': ArchitectAgent()
        }

    def run_project_agent(self, agent_name: str, project_id: int,
                          action: str = None, context: Dict = None) -> Dict:
        """运行指定智能体"""
        if agent_name not in self.agents:
            return {'error': f'未知智能体: {agent_name}'}

        agent = self.agents[agent_name]
        exec_context = context or {}
        exec_context['project_id'] = project_id
        if action:
            exec_context['action'] = action

        return agent.execute(exec_context)

    def run_all_agents(self, project_id: int) -> Dict:
        """运行所有智能体"""
        results = {}

        for agent_name, agent in self.agents.items():
            try:
                result = agent.execute({'project_id': project_id})
                results[agent_name] = result
            except Exception as e:
                results[agent_name] = {'error': str(e)}

        return results

    def daily_report_all_projects(self) -> Dict:
        """为所有项目生成日报"""
        projects = ProjectDAO.get_all()
        results = {}

        pm_agent = self.agents['project_manager']

        for project in projects:
            try:
                result = pm_agent._generate_daily_report(project['id'])
                results[project['id']] = result

                # 发送报告给项目负责人
                developers = DeveloperDAO.get_by_project(project['id'])
                for dev in developers:
                    if 'team_leader' in dev.get('role', ''):
                        self.send_message(
                            receiver_id=dev['id'],
                            title=f'📋 {project["name"]} 日报',
                            content=result.get('report', '')[:500],
                            msg_type='report'
                        )

            except Exception as e:
                results[project['id']] = {'error': str(e)}

        return results


# ========== 导出主要类 ==========

__all__ = [
    'BaseAgent',
    'ProgressTrackerAgent',
    'TestExpertAgent',
    'ProjectManagerAgent',
    'ArchitectAgent',
    'AgentScheduler',
    'call_llm'
]