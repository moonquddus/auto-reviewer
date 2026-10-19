from enum import Enum

PASSING = {"SUCCESS", "NEUTRAL", "SKIPPED"}
FAILING = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}


class Gate(Enum):
    OPEN = "open"
    PENDING = "pending"
    BLOCKED = "blocked"


def _state(check: dict) -> str:
    return (check.get("conclusion") or check.get("state") or check.get("status") or "").upper()


def evaluate(details: dict) -> tuple[Gate, str]:
    if details["isDraft"]:
        return Gate.BLOCKED, "draft"
    states = [_state(c) for c in details.get("statusCheckRollup") or []]
    if any(s in FAILING for s in states):
        return Gate.BLOCKED, "CI failed"
    if any(s not in PASSING for s in states):
        return Gate.PENDING, "CI pending"
    return Gate.OPEN, "ok"
