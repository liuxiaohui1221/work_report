"""Git collector for fetching commit data"""
import subprocess
from datetime import datetime, timedelta
from typing import List, Optional
from .base import BaseCollector
from ..storage.models import Commit, TimePeriod


class GitCollector(BaseCollector):
    """Collector for Git repository data"""

    def __init__(self, repo_path: str):
        super().__init__("git")
        self.repo_path = repo_path

    def get_commits(self, project_id: str, period: TimePeriod) -> List[Commit]:
        """Fetch commits from git repository"""
        cmd = [
            "git", "-C", self.repo_path, "log",
            f"--since={period.start.strftime('%Y-%m-%d')}",
            f"--until={period.end.strftime('%Y-%m-%d')}",
            "--pretty=format:%H|%h|%s|%an|%ae|%aI",
            "--date=iso"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if result.returncode != 0:
                return []

            commits = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 6:
                    commit = Commit(
                        commit_hash=parts[0],
                        short_hash=parts[1],
                        message=parts[2],
                        author_name=parts[3],
                        author_email=parts[4],
                        committed_at=datetime.fromisoformat(parts[5]),
                        project_id=project_id
                    )
                    commits.append(commit)
            return commits
        except Exception as e:
            print(f"Git fetch error: {e}")
            return []

    def get_commit_diff(self, commit_hash: str) -> str:
        """Get diff for a specific commit"""
        cmd = [
            "git", "-C", self.repo_path, "show", commit_hash, "--patch", "--pretty=format:"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
            return result.stdout if result.returncode == 0 else ""
        except Exception:
            return ""

    def get_tasks(self, project_id: str, period: TimePeriod) -> List:
        """Git collector doesn't provide tasks"""
        return []

    def get_activity_logs(self, person_id: str, project_id: str, period: TimePeriod):
        """Git collector provides commit activities"""
        return []  # Will be implemented via get_commits


class GitCollectorFactory:
    """Factory for creating Git collectors"""

    @staticmethod
    def create(repo_path: str) -> GitCollector:
        return GitCollector(repo_path)