import base64
import json
import re
import subprocess
import urllib.error
import urllib.request
from functools import cache

from auto_reviewer.config import JiraConfig

KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
MAX_TICKETS = 3
MAX_COMMENTS = 10
NOT_READ = "**note (non-blocking):** I could not review the intent, because I could not read the Jira ticket for this PR."


class JiraError(Exception):
    pass


def keys(*texts: str) -> list[str]:
    found = dict.fromkeys(k for t in texts for k in KEY.findall(t))
    return list(found)[:MAX_TICKETS]


@cache
def _token(service: str) -> str:
    token = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if not token:
        raise JiraError(f"Keychain item {service} is empty")
    return token


def _get(cfg: JiraConfig, key: str) -> dict | None:
    auth = base64.b64encode(f"{cfg.email}:{_token(cfg.token_keychain_service)}".encode()).decode()
    url = f"{cfg.base_url.rstrip('/')}/rest/api/2/issue/{key}?fields=summary,issuetype,status,description,parent,comment"
    request = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        # A key-like string that is not a ticket, e.g. "UTF-8", returns 404.
        if e.code == 404:
            return None
        raise JiraError(f"{key}: Jira returned {e.code}") from e
    except urllib.error.URLError as e:
        raise JiraError(f"{key}: {e.reason}") from e


def render(issue: dict) -> str:
    f = issue["fields"]
    lines = [f"{issue['key']} ({f['issuetype']['name']}, {f['status']['name']}): {f['summary']}"]
    if parent := f.get("parent"):
        lines.append(f"Parent: {parent['key']}: {parent['fields']['summary']}")
    lines.append(f"\n{f.get('description') or '(no description)'}")
    for c in (f.get("comment") or {}).get("comments", [])[-MAX_COMMENTS:]:
        lines.append(f"\nComment from {c['author']['displayName']}:\n{c['body']}")
    return "\n".join(lines)


def tickets(cfg: JiraConfig, *texts: str) -> str:
    if not cfg.base_url:
        return ""
    issues = [i for k in keys(*texts) if (i := _get(cfg, k))]
    return "\n\n---\n\n".join(render(i) for i in issues)
