import json
from pathlib import Path

import pytest

from auto_reviewer import actions, config, gates
from auto_reviewer.diff import commentable_lines
from auto_reviewer.reviewer import Comment, Review, ReviewError, earlier_threads, parse
from auto_reviewer.state import Seen
from auto_reviewer.watch import Tail, wrap

DIFF = """diff --git a/app.py b/app.py
index 111..222 100644
--- a/app.py
+++ b/app.py
@@ -1,3 +1,4 @@
 import os
-x = 1
+x = 2
+++y
 print(x)
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-gone
"""


def test_commentable_lines():
    assert commentable_lines(DIFF) == {("app.py", 1), ("app.py", 2), ("app.py", 3), ("app.py", 4)}


@pytest.mark.parametrize("info, reason", [
    ({"isDraft": True, "statusCheckRollup": []}, "draft"),
    ({"isDraft": False, "reviewDecision": "APPROVED"}, "approved"),
    ({"isDraft": False, "latestReviews": [{"state": "COMMENTED"}, {"state": "APPROVED"}]}, "approved"),
    ({"isDraft": False, "statusCheckRollup": [{"conclusion": "FAILURE"}]}, "CI failed"),
    ({"isDraft": False, "statusCheckRollup": [{"status": "IN_PROGRESS", "conclusion": ""}]}, "CI pending"),
    ({"isDraft": False, "statusCheckRollup": [{"state": "PENDING"}]}, "CI pending"),
    ({"isDraft": False, "statusCheckRollup": [{"conclusion": "SUCCESS"}, {"state": "SUCCESS"}]}, None),
    ({"isDraft": False, "statusCheckRollup": [], "latestReviews": [{"state": "CHANGES_REQUESTED"}]}, None),
])
def test_blocker(info, reason):
    assert gates.blocker(info) == reason


def test_blocker_ignores_ci_when_disabled():
    assert gates.blocker({"isDraft": False, "statusCheckRollup": [{"conclusion": "FAILURE"}]}, check_ci=False) is None


LINES = {("app.py", 2)}


def test_accept_without_comments_approves_empty():
    result = actions.settle(Review("accept", []), LINES)
    assert actions.payload(result, "sha") == {"commit_id": "sha", "event": "APPROVE"}


def test_accept_with_comments_approves_with_comments():
    result = actions.settle(Review("accept", [Comment("app.py", 2, "hm")]), LINES)
    assert actions.payload(result, "sha") == {
        "commit_id": "sha",
        "event": "APPROVE",
        "comments": [{"path": "app.py", "line": 2, "side": "RIGHT", "body": "hm"}],
    }


def test_accept_with_only_invalid_comments_approves_empty():
    result = actions.settle(Review("accept", [Comment("app.py", 99, "hm")]), LINES)
    assert actions.payload(result, "sha") == {"commit_id": "sha", "event": "APPROVE"}


def test_needs_changes_with_only_invalid_comments_posts_nothing():
    assert actions.settle(Review("needs_changes", [Comment("app.py", 99, "hm")]), LINES) is None


def test_invalid_comments_dropped():
    result = actions.settle(Review("needs_changes", [Comment("app.py", 2, "a"), Comment("x.py", 1, "b")]), LINES)
    assert actions.payload(result, "sha") == {
        "commit_id": "sha",
        "event": "REQUEST_CHANGES",
        "comments": [{"path": "app.py", "line": 2, "side": "RIGHT", "body": "a"}],
    }


def test_duplicate_of_earlier_comment_dropped():
    earlier = [{"path": "app.py", "body": "**issue (blocking):** Off by one.\n\nOld wording."}]
    review = Review("needs_changes", [Comment("app.py", 2, "**Issue (blocking):** Off by one.\n\nNew wording.")])
    assert actions.settle(review, LINES, earlier) is None


def test_new_comment_kept_next_to_earlier():
    earlier = [{"path": "app.py", "body": "**issue (blocking):** Off by one."}]
    review = Review("needs_changes", [Comment("app.py", 2, "**issue (blocking):** Null check missing.")])
    assert actions.settle(review, LINES, earlier).comments == review.comments


def test_earlier_threads():
    comments = [
        {"id": 1, "path": "a.py", "line": 3, "body": "**issue (blocking):** X.", "user": "me", "reply_to": None},
        {"id": 2, "path": "a.py", "line": 3, "body": "Fixed.", "user": "dev", "reply_to": 1},
        {"id": 3, "path": "b.py", "line": 1, "body": "Human note.", "user": "dev", "reply_to": None},
    ]
    assert earlier_threads(comments, "me") == "a.py:3\n**issue (blocking):** X.\nReply from dev: Fixed."


def test_parse_ok():
    out = json.dumps({"is_error": False, "structured_output": {"verdict": "accept", "comments": [
        {"path": "a.py", "line": 3, "label": "nitpick", "blocking": False, "subject": "Rename x.", "discussion": "Too short."},
        {"path": "a.py", "line": 4, "label": "issue", "blocking": True, "subject": "Off by one.", "discussion": " "}]}})
    assert parse(out) == Review("accept", [
        Comment("a.py", 3, "**nitpick (non-blocking):** Rename x.\n\nToo short."),
        Comment("a.py", 4, "**issue (blocking):** Off by one."),
    ])


@pytest.mark.parametrize("out", ["not json", json.dumps({"is_error": True, "result": "Not logged in"})])
def test_parse_errors(out):
    with pytest.raises(ReviewError):
        parse(out)


def test_seen_persists(tmp_path: Path):
    path = tmp_path / "seen.json"
    key = Seen.key("o/r", 1, "abc")
    Seen(path).add(key)
    assert key in Seen(path)
    assert Seen.key("o/r", 1, "def") not in Seen(path)


@pytest.mark.parametrize("allow", ["", "allow:\n", "allow:\n  authors: []\n  teams: []\n"])
def test_load_rejects_empty_allow(tmp_path: Path, allow):
    path = tmp_path / "config.yaml"
    path.write_text(allow)
    with pytest.raises(config.ConfigError):
        config.load(path)


def test_load_accepts_authors_only(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("allow:\n  authors: [alice]\n")
    assert config.load(path).authors == ["alice"]


def test_tail_reads_only_new_lines_and_handles_truncation(tmp_path):
    log_file = tmp_path / "a.log"
    log_file.write_text("old\n")
    tail = Tail(log_file)
    assert not tail.poll()
    with log_file.open("a") as f:
        f.write("one\ntw")
    assert tail.poll()
    assert list(tail.lines) == ["one"]
    with log_file.open("a") as f:
        f.write("o\nthree\n")
    tail.poll()
    assert list(tail.lines) == ["one", "two", "three"]
    log_file.write_text("new\n")
    tail.poll()
    assert list(tail.lines)[-1] == "new"


def test_wrap():
    assert wrap("abcdef", 4) == ["abcd", "ef"]
    assert wrap("", 4) == [""]
