import json
import subprocess
from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class PullRequest:
    repo: str
    number: int
    title: str
    author: str
    url: str


def _gh(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True, check=True).stdout


def viewer() -> str:
    return _gh("api", "user", "--jq", ".login").strip()


def assigned_prs() -> list[PullRequest]:
    rows = json.loads(_gh("search", "prs", "--assignee=@me", "--state=open", "--limit", "100",
                          "--json", "repository,number,title,author,url"))
    return [PullRequest(r["repository"]["nameWithOwner"], r["number"], r["title"], r["author"]["login"], r["url"])
            for r in rows]


@cache
def team_members(team: str) -> frozenset[str]:
    org, slug = team.split("/", 1)
    return frozenset(_gh("api", "--paginate", f"orgs/{org}/teams/{slug}/members", "--jq", ".[].login").split())


def details(pr: PullRequest) -> dict:
    return json.loads(_gh("pr", "view", str(pr.number), "--repo", pr.repo,
                          "--json", "headRefOid,isDraft,statusCheckRollup,body"))


def diff(pr: PullRequest) -> str:
    return _gh("pr", "diff", str(pr.number), "--repo", pr.repo)


def post_review(pr: PullRequest, payload: dict) -> None:
    _gh("api", "--method", "POST", f"repos/{pr.repo}/pulls/{pr.number}/reviews", "--input", "-",
        stdin=json.dumps(payload))
