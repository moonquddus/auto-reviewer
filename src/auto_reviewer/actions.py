from auto_reviewer.reviewer import Review

EVENTS = {"accept": "APPROVE", "needs_changes": "REQUEST_CHANGES"}


def settle(review: Review, commentable: set[tuple[str, int]]) -> Review | None:
    comments = [c for c in review.comments if (c.path, c.line) in commentable]
    if review.verdict == "needs_changes" and not comments:
        return None
    return Review(review.verdict, comments)


def payload(review: Review, sha: str) -> dict:
    body = {"commit_id": sha, "event": EVENTS[review.verdict]}
    if review.comments:
        body["comments"] = [{"path": c.path, "line": c.line, "side": "RIGHT", "body": c.body} for c in review.comments]
    return body
