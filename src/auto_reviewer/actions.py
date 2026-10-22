from auto_reviewer.reviewer import Review

EVENTS = {"accept": "APPROVE", "needs_changes": "REQUEST_CHANGES"}


def _head(path: str, body: str) -> tuple[str, str]:
    return path, body.strip().split("\n", 1)[0].lower()


def settle(review: Review, commentable: set[tuple[str, int]], earlier: list[dict] = ()) -> Review | None:
    posted = {_head(c["path"], c["body"]) for c in earlier}
    comments = [c for c in review.comments
                if (c.path, c.line) in commentable and _head(c.path, c.body) not in posted]
    if review.verdict == "needs_changes" and not comments:
        return None
    return Review(review.verdict, comments)


def payload(review: Review | None, sha: str, note: str = "") -> dict:
    # No review means nothing new to say, so post the note alone without changing the verdict.
    body = {"commit_id": sha, "event": EVENTS[review.verdict] if review else "COMMENT"}
    if note:
        body["body"] = note
    if review and review.comments:
        body["comments"] = [{"path": c.path, "line": c.line, "side": "RIGHT", "body": c.body} for c in review.comments]
    return body
