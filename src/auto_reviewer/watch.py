import curses
import re
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HISTORY = 1000
TITLE = "Auto Reviewer"
FOOTER = "Press q to exit"
POSTED = re.compile(r"^(\S+ \d\d:\d\d)\S* INFO (\S+): posted (\w+) with (\d+) comments(?:, author (\S+))?$")
STATUS = {"APPROVE": "Approved", "REQUEST_CHANGES": "Changes requested", "COMMENT": "Commented"}
HEADERS = ("Time", "Author", "PR", "Status", "Comments")


class Tail:
    def __init__(self, path: Path, from_start: bool = False) -> None:
        self.path = path
        self.lines: deque[str] = deque(maxlen=HISTORY)
        self.pos = path.stat().st_size if path.exists() and not from_start else 0
        self.partial = b""

    def poll(self) -> bool:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return False
        if size < self.pos:
            self.pos, self.partial = 0, b""
        if size == self.pos:
            return False
        with self.path.open("rb") as f:
            f.seek(self.pos)
            data = self.partial + f.read()
            self.pos = f.tell()
        *complete, self.partial = data.split(b"\n")
        self.lines.extend(line.decode(errors="replace").expandtabs() for line in complete)
        return bool(complete)


@dataclass(frozen=True)
class Posted:
    time: str
    author: str
    url: str
    status: str
    comments: str


def posted(line: str) -> Posted | None:
    if not (m := POSTED.search(line)):
        return None
    time, url, event, comments, author = m.groups()
    when = datetime.strptime(time, "%Y-%m-%d %H:%M")
    return Posted(f"{when.day} {when:%b %H:%M}", author or "-", url, STATUS.get(event, event), comments)


def table(rows: list[Posted], width: int) -> list[str]:
    cells = [HEADERS, *((r.time, r.author, r.url, r.status, r.comments) for r in rows)]
    widths = [max(map(len, col)) for col in zip(*cells)]
    link = HEADERS.index("PR")
    widths[link] = max(len(HEADERS[link]), min(widths[link], width - sum(widths) + widths[link] - 2 * (len(widths) - 1)))
    lines = ["  ".join(c[:w].ljust(w) for c, w in zip(row, widths)) for row in cells]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return lines


def wrap(line: str, width: int) -> list[str]:
    return [line[i : i + width] for i in range(0, len(line), width)] or [""]


def frame(win: curses.window, title: str) -> tuple[int, int]:
    win.box()
    h, w = win.getmaxyx()
    win.addnstr(0, 2, f" {title} ", w - 4, curses.A_BOLD)
    return h - 2, w - 2


def draw_table(win: curses.window, tail: Tail) -> None:
    inner_h, inner_w = frame(win, "Reviews")
    rows = [p for p in map(posted, reversed(tail.lines)) if p]
    for y, line in enumerate(table(rows, inner_w)[:inner_h], start=1):
        win.addnstr(y, 1, line, inner_w, curses.A_BOLD if y == 1 else curses.A_NORMAL)
    win.noutrefresh()


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


def draw(stdscr: curses.window, reviews: Tail, errors: Tail) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if h < 5 or w < 20:
        stdscr.noutrefresh()
        curses.doupdate()
        return
    stdscr.addnstr(0, max(0, (w - len(TITLE)) // 2), TITLE, w, curses.A_BOLD | curses.A_REVERSE)
    stdscr.addnstr(h - 1, max(0, (w - len(FOOTER)) // 2), FOOTER, w - 1, curses.A_DIM)
    stdscr.noutrefresh()
    left = w * 3 // 5
    draw_table(stdscr.derwin(h - 2, left, 1, 0), reviews)
    draw_log(stdscr.derwin(h - 2, w - left, 1, left), errors)
    curses.doupdate()


def run(stdscr: curses.window, reviews: Tail, errors: Tail) -> None:
    curses.curs_set(0)
    stdscr.timeout(200)
    dirty = True
    while True:
        dirty = any([reviews.poll(), errors.poll()]) or dirty
        if dirty:
            draw(stdscr, reviews, errors)
            dirty = False
        key = stdscr.getch()
        if key in (ord("q"), ord("Q")):
            return
        if key == curses.KEY_RESIZE:
            dirty = True


def main() -> None:
    reviews_log, errors_log = sys.argv[1:3]
    try:
        curses.wrapper(run, Tail(Path(reviews_log), from_start=True), Tail(Path(errors_log)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
