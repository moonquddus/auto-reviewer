from auto_reviewer.reviewer import Review

EVENTS = {"accept": "APPROVE", "comment": "COMMENT", "needs_changes": "REQUEST_CHANGES"}


def settle(review: Review, commentable: set[tuple[str, int]]) -> Review | None:
    verdict = "comment" if review.verdict == "accept" and review.comments else review.verdict
    comments = [c for c in review.comments if (c.path, c.line) in commentable]
    if verdict != "accept" and not comments:
        return None
    return Review(verdict, comments)


def payload(review: Review, sha: str) -> dict:
    body = {"commit_id": sha, "event": EVENTS[review.verdict]}
    if review.comments:
        body["comments"] = [{"path": c.path, "line": c.line, "side": "RIGHT", "body": c.body} for c in review.comments]
    return body
