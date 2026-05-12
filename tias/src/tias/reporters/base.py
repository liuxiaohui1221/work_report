"""Report generation module for TIAS"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, Optional
from ..storage.models import TimePeriod, Report
import json


class BaseReporter(ABC):
    """Abstract base class for all reporters"""

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    @abstractmethod
    def gather_data(self, period: TimePeriod, **kwargs) -> Dict[str, Any]:
        """Gather data for report generation"""
        pass

    @abstractmethod
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze gathered data"""
        pass

    @abstractmethod
    def generate_content(self, analysis: Dict[str, Any], **kwargs) -> str:
        """Generate report content"""
        pass

    def generate(self, period: TimePeriod, **kwargs) -> Report:
        """Generate complete report"""
        data = self.gather_data(period, **kwargs)
        analysis = self.analyze(data)
        content = self.generate_content(analysis, **kwargs)

        return Report(
            id=kwargs.get('report_id'),
            report_type=self.report_type,
            person_id=kwargs.get('person_id'),
            project_id=kwargs.get('project_id'),
            content=content,
            generated_at=datetime.now(),
            period_start=period.start,
            period_end=period.end,
        )


class HourlyReporter(BaseReporter):
    """Generate hourly reports"""

    report_type = "hourly"

    def gather_data(self, period: TimePeriod, **kwargs) -> Dict[str, Any]:
        return {
            "commits": kwargs.get("commits", []),
            "period": period.description
        }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "commit_count": len(data.get("commits", [])),
            "summary": f"共 {len(data.get('commits', []))} 次提交"
        }

    def generate_content(self, analysis: Dict[str, Any], **kwargs) -> str:
        return f"""# 小时报 - {analysis['period']}

## 汇总
{analysis['summary']}

## 提交记录
{chr(10).join([c.message for c in analysis.get('commits', [])]) or '无提交'}
"""


class DailyReporter(BaseReporter):
    """Generate daily reports"""

    report_type = "daily"

    def gather_data(self, period: TimePeriod, **kwargs) -> Dict[str, Any]:
        return {
            "commits": kwargs.get("commits", []),
            "tasks": kwargs.get("tasks", []),
            "period": period.description
        }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "commit_count": len(data.get("commits", [])),
            "task_count": len(data.get("tasks", [])),
            "period": data['period']
        }

    def generate_content(self, analysis: Dict[str, Any], **kwargs) -> str:
        return f"""# 日报 - {analysis['period']}

## 今日完成
- 提交数: {analysis['commit_count']}
- 任务数: {analysis['task_count']}

## 风险与阻塞
无

## 明日计划
-
"""


class WeeklyReporter(BaseReporter):
    """Generate weekly reports"""

    report_type = "weekly"

    def gather_data(self, period: TimePeriod, **kwargs) -> Dict[str, Any]:
        return {
            "commits": kwargs.get("commits", []),
            "tasks": kwargs.get("tasks", []),
            "period": period.description
        }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "commit_count": len(data.get("commits", [])),
            "task_count": len(data.get("tasks", [])),
            "period": data['period']
        }

    def generate_content(self, analysis: Dict[str, Any], **kwargs) -> str:
        return f"""# 周报 - {analysis['period']}

## 本周完成
- 提交数: {analysis['commit_count']}
- 任务数: {analysis['task_count']}

## 工作总结
整体进展顺利

## 下周计划
-

## 需协调与帮助
无
"""


class AIBriefingReporter(BaseReporter):
    """Generate AI-focused briefings for code agents"""

    report_type = "ai_briefing"

    def gather_data(self, period: TimePeriod, **kwargs) -> Dict[str, Any]:
        return {
            "commits": kwargs.get("commits", []),
            "tasks": kwargs.get("tasks", []),
            "project": kwargs.get("project", {}),
            "team": kwargs.get("team", []),
            "period": period.description
        }

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        commits = data.get("commits", [])
        return {
            "commit_count": len(commits),
            "recent_changes": [
                {
                    "hash": c.short_hash,
                    "message": c.message,
                    "author": c.author_name
                } for c in commits[-5:]
            ],
            "project": data.get("project", {}),
            "period": data['period']
        }

    def generate_content(self, analysis: Dict[str, Any], **kwargs) -> str:
        project = analysis.get("project", {})
        recent = analysis.get("recent_changes", [])

        return json.dumps({
            "briefing_type": "project_status_for_agent",
            "project": project,
            "period": analysis['period'],
            "commit_count": analysis['commit_count'],
            "recent_changes": recent,
            "context_for_agent": self._build_context(analysis)
        }, ensure_ascii=False, indent=2)

    def _build_context(self, analysis: Dict[str, Any]) -> str:
        project = analysis.get("project", {})
        return f"""项目 {project.get('name', 'unknown')} 当前进度报告：
- 本周期共 {analysis['commit_count']} 次提交
- 最近提交: {', '.join([c['message'] for c in analysis.get('recent_changes', [])[:3]])}"""