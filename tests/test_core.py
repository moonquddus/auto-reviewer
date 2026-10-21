import json
from pathlib import Path

import pytest

from auto_reviewer import actions, gates
from auto_reviewer.diff import commentable_lines
from auto_reviewer.reviewer import Comment, Review, ReviewError, parse
from auto_reviewer.state import Seen

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


def test_parse_ok():
    out = json.dumps({"is_error": False, "structured_output": {"verdict": "accept", "comments": [
        {"path": "a.py", "line": 3, "body": "b"}]}})
    assert parse(out) == Review("accept", [Comment("a.py", 3, "b")])


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
