"""Base collector interface for data ingestion"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional
from ..storage.models import Commit, Task, ActivityLog, TimePeriod


class BaseCollector(ABC):
    """Abstract base class for all data collectors"""

    def __init__(self, source_name: str):
        self.source_name = source_name

    @abstractmethod
    def get_commits(self, project_id: str, period: TimePeriod) -> List[Commit]:
        """Fetch commits for a project within time period"""
        pass

    @abstractmethod
    def get_tasks(self, project_id: str, period: TimePeriod) -> List[Task]:
        """Fetch tasks for a project within time period"""
        pass

    @abstractmethod
    def get_activity_logs(self, person_id: str, project_id: str, period: TimePeriod) -> List[ActivityLog]:
        """Fetch activity logs for a person/project within time period"""
        pass

    def parse_time_period(self, mode: str, manual_days: int = 1, morning_hour: int = 6, evening_hour: int = 12) -> TimePeriod:
        """Parse time period based on mode configuration"""
        now = datetime.now()
        current_hour = now.hour

        if mode == "manual":
            return TimePeriod(
                start=now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=manual_days),
                end=now,
                description=f"最近{manual_days}天"
            )
        else:  # auto
            if morning_hour <= current_hour < evening_hour:
                # Morning: fetch previous day
                yesterday = now - timedelta(days=1)
                return TimePeriod(
                    start=yesterday.replace(hour=0, minute=0, second=0, microsecond=0),
                    end=now.replace(hour=0, minute=0, second=0, microsecond=0),
                    description="昨天"
                )
            else:
                # Afternoon/Evening: fetch today
                return TimePeriod(
                    start=now.replace(hour=0, minute=0, second=0, microsecond=0),
                    end=now,
                    description="今天"
                )


from datetime import timedelta