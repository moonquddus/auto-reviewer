import curses
import re
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from auto_reviewer import herdr

HISTORY = 1000
TITLE = "Auto Reviewer"
FOOTER = "Press c to clear, d to toggle logs, q to exit"
POSTED = re.compile(r"^(\S+ \d\d:\d\d)\S* INFO (\S+): posted (\w+) with (\d+) comments(?:, author (\S+))?$")
STATUS = {"APPROVE": "Approved", "REQUEST_CHANGES": "Changes requested", "COMMENT": "Commented"}
HEADERS = ("Time", "Author", "PR", "Status", "Comments")
LINK = HEADERS.index("PR")
PULL = re.compile(r"([^/]+)/pull/(\d+)$")
EVENT = re.compile(r"^\S+ \S+ (INFO|ERROR) (\S+): (reviewing|posted|no new valid|dry run|)")


class Tail:
    def __init__(self, path: Path, from_start: bool = False) -> None:
        self.path = path
        self.lines: deque[str] = deque(maxlen=HISTORY)
        self.pos = path.stat().st_size if path.exists() and not from_start else 0
        self.partial = b""

    def poll(self) -> list[str]:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return []
        if size < self.pos:
            self.pos, self.partial = 0, b""
        if size == self.pos:
            return []
        with self.path.open("rb") as f:
            f.seek(self.pos)
            data = self.partial + f.read()
            self.pos = f.tell()
        *complete, self.partial = data.split(b"\n")
        new = [line.decode(errors="replace").expandtabs() for line in complete]
        self.lines.extend(new)
        return new


@dataclass(frozen=True)
class Posted:
    time: str
    author: str
    url: str
    status: str
    comments: str


@dataclass(frozen=True)
class Link:
    y: int
    x: int
    text: str
    url: str


def posted(line: str) -> Posted | None:
    if not (m := POSTED.search(line)):
        return None
    time, url, event, comments, author = m.groups()
    when = datetime.strptime(time, "%Y-%m-%d %H:%M")
    return Posted(f"{when.day} {when:%b %H:%M}", author or "-", url, STATUS.get(event, event), comments)


def short(url: str) -> str:
    return f"{m[1]}#{m[2]}" if (m := PULL.search(url)) else url


@dataclass(frozen=True)
class Event:
    state: str
    text: str
    toast: tuple[str, str] | None = None


def event(line: str) -> Event | None:
    if p := posted(line):
        title = f"{p.status} {short(p.url)}"
        return Event("idle", title, (title, f"{p.author}, {p.comments} comments"))
    if not (m := EVENT.match(line)):
        return None
    level, url, kind = m.groups()
    if level == "ERROR":
        return Event("idle", f"Failed {short(url)}")
    if kind == "reviewing":
        return Event("working", f"Reviewing {short(url)}")
    return Event("idle", f"Checked {short(url)}") if kind else None


def report(lines: list[str]) -> None:
    for e in filter(None, map(event, lines)):
        herdr.status(e.state, e.text)
        if e.toast:
            herdr.notify(*e.toast)


def layout(rows: list[Posted], width: int) -> tuple[list[tuple[str, ...]], list[int]]:
    cells = [HEADERS, *((r.time, r.author, r.url, r.status, r.comments) for r in rows)]
    widths = [max(map(len, col)) for col in zip(*cells)]
    if sum(widths) + 2 * (len(widths) - 1) > width:
        cells[1:] = [(*c[:LINK], short(c[LINK]), *c[LINK + 1 :]) for c in cells[1:]]
        widths = [max(map(len, col)) for col in zip(*cells)]
    widths[LINK] = max(len(HEADERS[LINK]), min(widths[LINK], width - sum(widths) + widths[LINK] - 2 * (len(widths) - 1)))
    return cells, widths


def table(rows: list[Posted], width: int) -> list[str]:
    cells, widths = layout(rows, width)
    lines = ["  ".join(c[:w].ljust(w) for c, w in zip(row, widths)) for row in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return lines


def links(rows: list[Posted], width: int) -> list[Link]:
    cells, widths = layout(rows, width)
    x = sum(widths[:LINK]) + 2 * LINK
    shown = max(0, min(widths[LINK], width - x))
    return [Link(y, x, c[LINK][:shown], r.url) for y, (c, r) in enumerate(zip(cells[1:], rows), start=2) if shown]


def hyperlink(link: Link, top: int, left: int) -> str:
    return f"\x1b[{top + link.y + 1};{left + link.x + 1}H\x1b]8;;{link.url}\x1b\\{link.text}\x1b]8;;\x1b\\"


def wrap(line: str, width: int) -> list[str]:
    return [line[i : i + width] for i in range(0, len(line), width)] or [""]


def frame(win: curses.window, title: str) -> tuple[int, int]:
    win.box()
    h, w = win.getmaxyx()
    win.addnstr(0, 2, f" {title} ", w - 4, curses.A_BOLD)
    return h - 2, w - 2


def draw_table(win: curses.window, tail: Tail) -> str:
    inner_h, inner_w = frame(win, "Reviews")
    rows = [p for p in map(posted, reversed(tail.lines)) if p]
    for y, line in enumerate(table(rows, inner_w)[:inner_h], start=1):
        win.addnstr(y, 1, line, inner_w, curses.A_BOLD if y == 1 else curses.A_NORMAL)
    win.noutrefresh()
    top, left = win.getbegyx()
    return "".join(hyperlink(link, top + 1, left + 1) for link in links(rows, inner_w) if link.y < inner_h)


def draw_log(win: curses.window, tail: Tail) -> None:
    inner_h, inner_w = frame(win, tail.path.name)
    rows: list[str] = []
    for line in reversed(tail.lines):
        rows[:0] = wrap(line, inner_w)
        if len(rows) >= inner_h:
            break
    for y, row in enumerate(rows[-inner_h:], start=1):
        win.addnstr(y, 1, row, inner_w)
    win.noutrefresh()


def draw(stdscr: curses.window, reviews: Tail, errors: Tail, show_log: bool) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if h < 5 or w < 20:
        stdscr.noutrefresh()
        curses.doupdate()
        return
    stdscr.addnstr(0, max(0, (w - len(TITLE)) // 2), TITLE, w, curses.A_BOLD | curses.A_REVERSE)
    stdscr.addnstr(h - 1, max(0, (w - len(FOOTER)) // 2), FOOTER, w - 1, curses.A_DIM)
    stdscr.noutrefresh()
    left = w * 3 // 5 if show_log else w
    escapes = draw_table(stdscr.derwin(h - 2, left, 1, 0), reviews)
    if show_log:
        draw_log(stdscr.derwin(h - 2, w - left, 1, left), errors)
    curses.doupdate()
    # curses cannot write OSC 8 hyperlinks, so overwrite the PR cells after the update, then put the cursor back
    y, x = curses.getsyx()
    sys.stdout.write(f"{escapes}\x1b[{y + 1};{x + 1}H")
    sys.stdout.flush()


def run(stdscr: curses.window, reviews: Tail, errors: Tail) -> None:
    curses.curs_set(0)
    stdscr.timeout(200)
    dirty = show_log = True
    reviews.poll()
    herdr.status("idle", "Auto Reviewer")
    while True:
        new = reviews.poll()
        report(new)
        dirty = any([new, errors.poll()]) or dirty
        if dirty:
            draw(stdscr, reviews, errors, show_log)
            dirty = False
        key = stdscr.getch()
        if key in (ord("q"), ord("Q")):
            return
        if key in (ord("c"), ord("C")):
            reviews.lines.clear()
            errors.lines.clear()
            dirty = True
        if key in (ord("d"), ord("D")):
            show_log = not show_log
            dirty = True
        if key == curses.KEY_RESIZE:
            dirty = True


def main() -> None:
    reviews_log, errors_log = sys.argv[1:3]
    try:
        curses.wrapper(run, Tail(Path(reviews_log), from_start=True), Tail(Path(errors_log)))
    except KeyboardInterrupt:
        pass
    finally:
        herdr.release()


if __name__ == "__main__":
    main()
