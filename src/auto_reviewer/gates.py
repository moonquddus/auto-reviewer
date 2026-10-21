PASSING = {"SUCCESS", "NEUTRAL", "SKIPPED"}
FAILING = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}


def _state(check: dict) -> str:
    return (check.get("conclusion") or check.get("state") or check.get("status") or "").upper()


def _approved(details: dict) -> bool:
    return details.get("reviewDecision") == "APPROVED" or any(
        r.get("state") == "APPROVED" for r in details.get("latestReviews") or [])


def blocker(details: dict, check_ci: bool = True) -> str | None:
    if details["isDraft"]:
        return "draft"
    if _approved(details):
        return "approved"
    if not check_ci:
        return None
    states = [_state(c) for c in details.get("statusCheckRollup") or []]
    if any(s in FAILING for s in states):
        return "CI failed"
    if any(s not in PASSING for s in states):
        return "CI pending"
    return None
