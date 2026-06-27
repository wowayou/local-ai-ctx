from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import Project, Surface


def detect_surface() -> Surface:
    try:
        version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
        if "microsoft" in version:
            return Surface.WSL
    except OSError:
        pass
    return Surface.UNKNOWN


def resolve_project_path(project: Project, surface: Surface) -> str | None:
    config = project.surfaces.get(surface)
    if config is not None and config.path:
        return config.path
    return None


@dataclass(frozen=True)
class GitState:
    path: str
    exists: bool
    is_repo: bool
    branch: str | None = None
    upstream: str | None = None
    upstream_exists: bool = False
    ahead: int = 0
    behind: int = 0
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0

    @property
    def diverged(self) -> bool:
        return self.ahead > 0 and self.behind > 0

    @property
    def dirty(self) -> bool:
        return self.staged > 0 or self.unstaged > 0

    @property
    def any_issues(self) -> bool:
        return (
            self.dirty
            or self.ahead > 0
            or self.behind > 0
            or not self.upstream_exists
        )


def check_git(path: str) -> GitState:
    if not os.path.exists(path):
        return GitState(path=path, exists=False, is_repo=False)

    result = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=path)
    if result is None or result.strip() != "true":
        return GitState(path=path, exists=True, is_repo=False)

    branch_raw = _run_git(["symbolic-ref", "--short", "HEAD"], cwd=path)
    branch = branch_raw.strip() if branch_raw is not None else None

    upstream_raw = _run_git(["rev-parse", "--abbrev-ref", "@{u}"], cwd=path)
    upstream = upstream_raw.strip() if upstream_raw is not None else None
    upstream_exists = bool(upstream)

    ahead = 0
    behind = 0
    if upstream_exists:
        ahead_raw = _run_git(["rev-list", "--count", "@{u}..HEAD"], cwd=path)
        if ahead_raw is not None:
            try:
                ahead = int(ahead_raw.strip())
            except ValueError:
                pass
        behind_raw = _run_git(["rev-list", "--count", "HEAD..@{u}"], cwd=path)
        if behind_raw is not None:
            try:
                behind = int(behind_raw.strip())
            except ValueError:
                pass

    staged = 0
    unstaged = 0
    untracked = 0
    status_raw = _run_git(["status", "--porcelain"], cwd=path)
    if status_raw is not None:
        for line in status_raw.splitlines():
            if len(line) < 2:
                continue
            if line[:2] == "??":
                untracked += 1
            else:
                if line[0] != " ":
                    staged += 1
                if line[1] != " ":
                    unstaged += 1

    return GitState(
        path=path,
        exists=True,
        is_repo=True,
        branch=branch,
        upstream=upstream,
        upstream_exists=upstream_exists,
        ahead=ahead,
        behind=behind,
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
    )


def _run_git(args: list[str], *, cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except (OSError, subprocess.TimeoutExpired):
        return None
