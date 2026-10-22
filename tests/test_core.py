import json
from pathlib import Path

import pytest

from auto_reviewer import actions, config, gates, jira
from auto_reviewer.diff import commentable_lines
from auto_reviewer.reviewer import Comment, Review, ReviewError, build_prompt, earlier_threads, parse
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


def test_payload_adds_note_as_review_body():
    result = actions.settle(Review("accept", []), LINES)
    assert actions.payload(result, "sha", "n") == {"commit_id": "sha", "event": "APPROVE", "body": "n"}


def test_note_without_review_is_a_comment():
    assert actions.payload(None, "sha", "n") == {"commit_id": "sha", "event": "COMMENT", "body": "n"}


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
    assert config.load(path).poll_seconds == 120


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


def test_jira_keys():
    assert jira.keys("ABC-123: Add login", "ABC-123-add-login", "https://x.atlassian.net/browse/ABC-45 utf-8") == ["ABC-123", "ABC-45"]


def test_jira_render():
    issue = {"key": "ABC-1", "fields": {
        "summary": "Add a login page", "issuetype": {"name": "Story"}, "status": {"name": "To Do"},
        "description": "Users sign in with email", "parent": {"key": "ABC-0", "fields": {"summary": "Epic"}},
        "comment": {"comments": [{"author": {"displayName": "Ann"}, "body": "Keep the old page"}]},
    }}
    assert jira.render(issue) == (
        "ABC-1 (Story, To Do): Add a login page\nParent: ABC-0: Epic\n\nUsers sign in with email"
        "\n\nComment from Ann:\nKeep the old page"
    )


def test_jira_off_without_base_url():
    assert jira.tickets(config.JiraConfig(), "ABC-1") == ""


def test_prompt_puts_tickets_before_diff():
    prompt = build_prompt("t", "b", "d", tickets="ABC-1")
    assert prompt.index("<jira_tickets>") < prompt.index("<diff>")
    assert "<jira_tickets>" not in build_prompt("t", "b", "d")


@pytest.fixture
def run_process(monkeypatch, tmp_path):
    from auto_reviewer import __main__ as main, github, jira

    def run(earlier_reviews, verdict):
        posted = []
        monkeypatch.setattr(github, "details", lambda pr: {"headRefOid": "sha", "headRefName": "x", "isDraft": False})
        monkeypatch.setattr(github, "diff", lambda pr: DIFF)
        monkeypatch.setattr(github, "review_comments", lambda pr: [])
        monkeypatch.setattr(github, "reviews", lambda pr: earlier_reviews)
        monkeypatch.setattr(github, "post_review", lambda pr, body: posted.append(body))
        monkeypatch.setattr(jira, "tickets", lambda *a: "")
        monkeypatch.setattr(main, "review", lambda *a: Review(verdict, []))
        cfg = config.Config(dry_run=False, check_ci=False, jira=config.JiraConfig(base_url="https://x"))
        pr = github.PullRequest("o/r", 1, "t", "a", "u")
        state = tmp_path / "state.json"
        state.unlink(missing_ok=True)
        main.process(cfg, Seen(state), pr, "me")
        return posted

    return run


def test_note_posted_alone_when_review_has_nothing_new(run_process):
    assert run_process([], "needs_changes") == [{"commit_id": "sha", "event": "COMMENT", "body": jira.NOT_READ}]


def test_note_not_repeated(run_process):
    assert run_process([{"user": "me", "body": jira.NOT_READ}], "accept") == [{"commit_id": "sha", "event": "APPROVE"}]
    assert run_process([{"user": "me", "body": jira.NOT_READ}], "needs_changes") == []
