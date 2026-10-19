import re

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def commentable_lines(diff: str) -> set[tuple[str, int]]:
    lines: set[tuple[str, int]] = set()
    path: str | None = None
    in_header = False
    line = 0
    for row in diff.splitlines():
        if row.startswith("diff --git "):
            in_header, path = True, None
        elif in_header and row.startswith("+++ "):
            target = row[4:]
            path = None if target == "/dev/null" else target.removeprefix("b/")
        elif match := HUNK.match(row):
            in_header, line = False, int(match.group(1))
        elif not in_header and path and row[:1] in ("+", " "):
            lines.add((path, line))
            line += 1
    return lines
