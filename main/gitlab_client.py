#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitLab API 客户端
用于从 GitLab 服务器获取用户提交记录，按项目分类汇总
"""

import os
import subprocess
import shutil
import tempfile
from datetime import datetime
from typing import Optional


class GitLabClient:
    """GitLab API 客户端"""

    def __init__(self, gitlab_url: str, private_token: str):
        self.gitlab_url = gitlab_url.rstrip("/")
        self.private_token = private_token
        self.api_base = f"{self.gitlab_url}/api/v4"

    def _request(self, endpoint: str, params: dict = None) -> dict:
        """发送 GET 请求到 GitLab API"""
        import httpx

        url = f"{self.api_base}/{endpoint.lstrip('/')}"
        headers = {"PRIVATE-TOKEN": self.private_token} if self.private_token else {}

        try:
            response = httpx.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            print(f"[ERROR] GitLab API 请求失败: {url}, error: {e}")
            return {}

    def search_user_by_email(self, email: str) -> Optional[dict]:
        """通过邮箱搜索用户"""
        users = self._request("users", params={"search": email})
        if isinstance(users, list):
            for user in users:
                if user.get("email") == email or user.get("username") == email:
                    return user
        return users[0] if users else None

    def list_user_projects(self, user_email: str, page: int = 1, per_page: int = 20) -> list:
        """列出用户在 GitLab 上有权限的所有项目（分页）"""
        # 通过邮箱找到用户 ID
        user = self.search_user_by_email(user_email)
        if not user:
            print(f"[WARN] 未找到用户: {user_email}")
            return []

        user_id = user["id"]
        all_projects = []
        current_page = page

        while True:
            projects = self._request(
                "projects",
                params={
                    "membership": True,
                    "simple": True,
                    "per_page": per_page,
                    "page": current_page,
                    "order_by": "last_activity_at",
                    "sort": "desc"
                }
            )
            if not projects:
                break

            for p in projects:
                all_projects.append({
                    "id": p["id"],
                    "name": p["name"],
                    "path_with_namespace": p["path_with_namespace"],
                    "web_url": p["web_url"],
                    "avatar_url": p.get("avatar_url"),
                    "last_activity_at": p.get("last_activity_at")
                })

            if len(projects) < per_page:
                break

            current_page += 1

        print(f"[INFO] 用户 {user_email} (ID:{user_id}) 在 GitLab 上有 {len(all_projects)} 个项目")
        return all_projects

    def get_project_commits(self, project_id: int, user_email: str, since: str, until: str) -> list:
        """获取指定项目指定用户的提交记录"""
        commits = self._request(
            f"projects/{project_id}/repository/commits",
            params={
                "since": since,
                "until": until,
                "author": user_email,
                "per_page": 100
            }
        )
        return commits if isinstance(commits, list) else []

    def get_project_diff(self, project_id: int, user_email: str, since: str, until: str, max_lines: int = 10000) -> str:
        """获取指定项目指定用户的代码变更"""
        tmpdir = self._clone_project(project_id)
        if not tmpdir:
            return "错误: 无法克隆远程仓库"

        try:
            cmd = [
                "git", "-C", tmpdir, "log", "--all",
                f"--since={since}", f"--until={until}",
                f"--author={user_email}",
                "--patch",
                "--pretty=format:"
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            if result.returncode == 0:
                diff = result.stdout.strip()
                if not diff:
                    return "本周无代码变更"
                lines = diff.split('\n')
                if len(lines) > max_lines:
                    return "\n".join(lines[:max_lines]) + f"\n... (diff 内容过长，已截断，仅显示前 {max_lines} 行)"
                return diff
            return "获取diff失败"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _clone_project(self, project_id: int) -> Optional[str]:
        """浅克隆指定项目到临时目录"""
        import httpx

        # 获取项目信息以构建克隆 URL
        project = self._request(f"projects/{project_id}", params={"simple": True})
        if not project:
            return None

        http_url_to_repo = project.get("http_url_to_repo")
        if not http_url_to_repo:
            return None

        tmpdir = tempfile.mkdtemp(prefix="gitlab_query_")
        try:
            # 使用浅克隆，仅获取最新提交
            result = subprocess.run(
                ["git", "clone", "--depth=100", "--filter=blob:limit=0", http_url_to_repo, tmpdir],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=120
            )
            if result.returncode != 0:
                shutil.rmtree(tmpdir, ignore_errors=True)
                return None
            return tmpdir
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None

    def get_user_commits_across_projects(self, user_email: str, since: str, until: str) -> dict:
        """
        获取用户在所有项目中的提交记录，按项目分类
        返回格式:
        {
            "project_path": {
                "id": 123,
                "name": "project",
                "web_url": "...",
                "commits": [...],
                "diff": "..."
            }
        }
        """
        projects = self.list_user_projects(user_email)
        result = {}

        for project in projects:
            project_id = project["id"]
            project_path = project["path_with_namespace"]

            print(f"[DEBUG] 获取项目 {project_path} 的提交记录...")

            commits = self.get_project_commits(project_id, user_email, since, until)
            diff = self.get_project_diff(project_id, user_email, since, until)

            # 格式化提交记录
            formatted_commits = []
            for commit in commits:
                commit_hash = commit.get("id", "")[:12]
                message = commit.get("message", "").split("\n")[0]
                author_name = commit.get("author_name", "")
                author_date = commit.get("created_at", "")[:10]
                # 生成可点击的 GitLab commit 链接
                commit_url = f"{project['web_url']}/-/commit/{commit_hash}"
                formatted_commits.append(
                    f"- [{commit_hash}]({commit_url}) {message} ({author_name}, {author_date})"
                )

            result[project_path] = {
                "id": project_id,
                "name": project["name"],
                "web_url": project["web_url"],
                "commits": "\n".join(formatted_commits) if formatted_commits else "本周无提交记录",
                "diff": diff
            }

        return result


def get_user_gitlab_projects(user_email: str, gitlab_url: str, private_token: str) -> list:
    """从 GitLab 获取用户有权限的所有项目"""
    client = GitLabClient(gitlab_url, private_token)
    return client.list_user_projects(user_email)


def get_user_commits_from_gitlab(gitlab_url: str, private_token: str, user_email: str,
                                  since: str, until: str) -> dict:
    """获取用户在 GitLab 所有项目中的提交记录，按项目分类汇总"""
    client = GitLabClient(gitlab_url, private_token)
    return client.get_user_commits_across_projects(user_email, since, until)
