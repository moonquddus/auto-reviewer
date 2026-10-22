import argparse
import json
import logging
import subprocess
from dataclasses import replace
from pathlib import Path

from auto_reviewer import actions, config, gates, github
from auto_reviewer.diff import commentable_lines
from auto_reviewer.reviewer import ReviewError, build_prompt, earlier_threads, review
from auto_reviewer.state import DRY_RUN_STATE, STATE, Seen

LOG = Path.home() / "Library/Logs/auto-reviewer.log"
log = logging.getLogger("auto-reviewer")


def allowed(cfg: config.Config, author: str) -> bool:
    return author in cfg.authors or any(author in github.team_members(t) for t in cfg.teams)


def process(cfg: config.Config, seen: Seen, pr: github.PullRequest, me: str) -> None:
    info = github.details(pr)
    key = Seen.key(pr.repo, pr.number, info["headRefOid"])
    if key in seen:
        return
    if reason := gates.blocker(info, cfg.check_ci):
        log.debug("%s: skipped, %s", pr.url, reason)
        return

    diff = github.diff(pr)
    comments = github.review_comments(pr)
    mine = [c for c in comments if c["user"] == me]
    prompt = build_prompt(pr.title, info.get("body") or "", diff[: cfg.max_diff_bytes], earlier_threads(comments, me))
    result = actions.settle(review(cfg.claude, cfg.guide_for(pr.repo), prompt), commentable_lines(diff), mine)
    if result is None:
        log.info("%s: no new valid inline comments, nothing posted", pr.url)
        seen.add(key)
        return

    body = actions.payload(result, info["headRefOid"])
    if cfg.dry_run:
        log.info("%s: dry run %s", pr.url, json.dumps(body))
    else:
        github.post_review(pr, body)
        log.info("%s: posted %s with %d comments", pr.url, body["event"], len(result.comments))
    seen.add(key)


def main() -> None:
    parser = argparse.ArgumentParser(prog="auto-reviewer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", type=Path, default=config.ROOT / "config.yaml")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG), logging.StreamHandler()],
    )
    cfg = config.load(args.config)
    if args.dry_run:
        cfg = replace(cfg, dry_run=True)

    me = github.viewer()
    seen = Seen(DRY_RUN_STATE if cfg.dry_run else STATE)
    for pr in github.review_prs():
        if pr.author == me or not allowed(cfg, pr.author):
            continue
        try:
            process(cfg, seen, pr, me)
        except (ReviewError, subprocess.SubprocessError) as e:
            stderr = getattr(e, "stderr", "") or ""
            log.error("%s: %s %s", pr.url, e, stderr.strip())


if __name__ == "__main__":
    main()
