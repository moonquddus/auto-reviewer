from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ClaudeConfig:
    auth: Literal["login", "token"] = "login"
    token_keychain_service: str = "auto-reviewer-claude-token"
    model: str = "sonnet"
    timeout_seconds: int = 600


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

    def guide_for(self, repo: str) -> str:
        return self.repo_guides.get(repo, self.review_guide).read_text()


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else ROOT / p


class ConfigError(Exception):
    pass


def load(path: Path = ROOT / "config.yaml") -> Config:
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
        review_guide=_resolve(raw.get("review_guide", "review-guide.md")),
        repo_guides={repo: _resolve(p) for repo, p in (raw.get("repo_guides") or {}).items()},
        claude=ClaudeConfig(**(raw.get("claude") or {})),
    )
