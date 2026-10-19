import json
from pathlib import Path

STATE_DIR = Path.home() / ".local/state/auto-reviewer"
STATE = STATE_DIR / "seen.json"
DRY_RUN_STATE = STATE_DIR / "seen-dry-run.json"


class Seen:
    def __init__(self, path: Path = STATE):
        self.path = path
        self.keys: set[str] = set(json.loads(path.read_text())) if path.exists() else set()

    @staticmethod
    def key(repo: str, number: int, sha: str) -> str:
        return f"{repo}#{number}@{sha}"

    def __contains__(self, key: str) -> bool:
        return key in self.keys

    def add(self, key: str) -> None:
        self.keys.add(key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(self.keys)))
