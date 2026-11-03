import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

ROOT = Path(__file__).resolve().parents[2]
DIR_ENVS = ("AUTO_REVIEWER_CONFIG_DIR", "HERDR_PLUGIN_CONFIG_DIR")


@dataclass(frozen=True)
class ClaudeConfig:
    auth: Literal["login", "token"] = "login"
    token_keychain_service: str = "auto-reviewer-claude-token"
    model: str = "sonnet"
    timeout_seconds: int = 600


@dataclass(frozen=True)
class JiraConfig:
    base_url: str = ""
    email: str = ""
    token_keychain_service: str = "auto-reviewer-jira-token"


@dataclass(frozen=True)
class Config:
    dry_run: bool = True
    check_ci: bool = True
    poll_seconds: int = 120
    authors: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)
    max_diff_bytes: int = 200_000
    review_guide: Path = ROOT / "review-guide.md"
    repo_guides: dict[str, Path] = field(default_factory=dict)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    jira: JiraConfig = field(default_factory=JiraConfig)

    def guide_for(self, repo: str) -> str:
        return self.repo_guides.get(repo, self.review_guide).read_text()


def directory() -> Path:
    dirs = [Path(d) for d in map(os.environ.get, DIR_ENVS) if d] + [ROOT]
    return next((d for d in dirs if (d / "config.yaml").exists()), dirs[0])


def _resolve(path: str, base: Path) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    return next((d / p for d in (base, ROOT) if (d / p).exists()), base / p)


class ConfigError(Exception):
    pass


def load(path: Path | None = None) -> Config:
    path = path or directory() / "config.yaml"
    if not path.exists():
        raise ConfigError(f"Missing {path}. Copy config.example.yaml there first.")
    raw = yaml.safe_load(path.read_text()) or {}
    allow = raw.get("allow", {}) or {}
    if not allow.get("authors") and not allow.get("teams"):
        raise ConfigError(f"{path}: set allow.authors or allow.teams, or both")
    return Config(
        dry_run=raw.get("dry_run", True),
        check_ci=raw.get("check_ci", True),
        poll_seconds=raw.get("poll_seconds", 120),
        authors=allow.get("authors", []) or [],
        teams=allow.get("teams", []) or [],
        max_diff_bytes=raw.get("max_diff_bytes", 200_000),
        review_guide=_resolve(raw.get("review_guide", "review-guide.md"), path.parent),
        repo_guides={repo: _resolve(p, path.parent) for repo, p in (raw.get("repo_guides") or {}).items()},
        claude=ClaudeConfig(**(raw.get("claude") or {})),
        jira=JiraConfig(**(raw.get("jira") or {})),
    )
