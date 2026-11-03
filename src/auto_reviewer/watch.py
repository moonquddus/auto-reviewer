import curses
import os
import re
import select
import sys
import termios
import tty
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from auto_reviewer import herdr

HISTORY = 1000
TITLE = "Auto Reviewer"
FOOTER = (("Ctrl+Click", "Open PR"), ("c", "clear"), ("d", "debug"), ("q", "quit"))
POSTED = re.compile(r"^(\S+ \d\d:\d\d)\S* INFO (\S+): posted (\w+) with (\d+) comments(?:, author (\S+))?$")
STATUS = {"APPROVE": "Approved", "REQUEST_CHANGES": "Changes requested", "COMMENT": "Commented"}
HEADERS = ("Time", "Author", "PR", "Status", "Comments")
LINK = HEADERS.index("PR")
CENTERED = {"Status", "Comments"}
ALIGN = [str.center if h in CENTERED else str.ljust for h in HEADERS]
FLAG = HEADERS.index("Status")
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
class Style:
    header: int = curses.A_BOLD
    flag: int = curses.A_REVERSE
    flag_sgr: str = "\x1b[7m"


@dataclass(frozen=True)
class Theme:
    header_bg: int
    flag_fg: int
    flag_bg: int


DARK = Theme(header_bg=236, flag_fg=15, flag_bg=88)
LIGHT = Theme(header_bg=253, flag_fg=0, flag_bg=196)


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
    return ["  ".join(a(c[:w], w) for a, c, w in zip(ALIGN, row, widths)) for row in cells]


def span(widths: list[int], col: int) -> tuple[int, int]:
    start = sum(widths[:col]) + 2 * col
    return start, start + widths[col]


def flagged(rows: list[Posted]) -> set[int]:
    latest = {}
    for i, r in enumerate(rows):
        latest.setdefault(r.url, i)
    return {i for i in latest.values() if rows[i].status == STATUS["REQUEST_CHANGES"]}


def linked_row(y: int, x: int, line: str, url: str, flag: tuple[int, int] | None, sgr: str) -> str:
    body = f"{line[: flag[0]]}{sgr}{line[flag[0] : flag[1]]}\x1b[0m{line[flag[1] :]}" if flag else line
    return f"\x1b[{y + 1};{x + 1}H\x1b]8;;{url}\x1b\\{body}\x1b]8;;\x1b\\"


def wrap(line: str, width: int) -> list[str]:
    return [line[i : i + width] for i in range(0, len(line), width)] or [""]


def frame(win: curses.window, title: str) -> tuple[int, int]:
    win.box()
    h, w = win.getmaxyx()
    win.addnstr(0, 2, f" {title} ", w - 4, curses.A_BOLD)
    return h - 2, w - 2


def draw_table(win: curses.window, tail: Tail, boxed: bool, style: Style) -> str:
    h, w = win.getmaxyx()
    # curses fails on a write to the bottom-right cell, so keep one free column without a box
    (inner_h, inner_w), pad = (frame(win, "Reviews"), 1) if boxed else ((h, w - 1), 0)
    rows = [p for p in map(posted, reversed(tail.lines)) if p]
    _, widths = layout(rows, inner_w)
    start, end = span(widths, FLAG)
    flag = (min(start, inner_w), min(end, inner_w))
    alerts = flagged(rows)
    top, left = win.getbegyx()
    escapes = []
    for y, line in enumerate(table(rows, inner_w)[:inner_h]):
        line = line[:inner_w].ljust(inner_w)
        win.addnstr(y + pad, pad, line, inner_w, style.header if y == 0 else curses.A_NORMAL)
        if y == 0:
            continue
        cell = flag if y - 1 in alerts else None
        if cell:
            win.chgat(y + pad, pad + cell[0], cell[1] - cell[0], style.flag)
        escapes.append(linked_row(top + pad + y, left + pad, line, rows[y - 1].url, cell, style.flag_sgr))
    win.noutrefresh()
    return "".join(escapes)


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


def draw_footer(win: curses.window, y: int, w: int) -> None:
    italic = getattr(curses, "A_ITALIC", curses.A_NORMAL)
    parts = []
    for i, (key, label) in enumerate(FOOTER):
        parts += [(" | " if i else "", curses.A_DIM), (key, curses.A_BOLD), (f": {label}", italic)]
    x = max(0, (w - sum(len(t) for t, _ in parts)) // 2)
    for text, attr in parts:
        if text and x < w - 1:
            win.addnstr(y, x, text, w - 1 - x, attr)
        x += len(text)


def draw(stdscr: curses.window, reviews: Tail, errors: Tail, show_log: bool, style: Style) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if h < 5 or w < 20:
        stdscr.noutrefresh()
        curses.doupdate()
        return
    top = 0 if herdr.enabled() else 1
    if top:
        stdscr.addnstr(0, max(0, (w - len(TITLE)) // 2), TITLE, w, curses.A_BOLD | curses.A_REVERSE)
    draw_footer(stdscr, h - 1, w)
    stdscr.noutrefresh()
    left = w * 3 // 5 if show_log else w
    escapes = draw_table(stdscr.derwin(h - 1 - top, left, top, 0), reviews, bool(top), style)
    if show_log:
        draw_log(stdscr.derwin(h - 1 - top, w - left, top, left), errors)
    curses.doupdate()
    # curses cannot write OSC 8 hyperlinks, so overwrite the rows after the update, then put the cursor back
    y, x = curses.getsyx()
    sys.stdout.write(f"{escapes}\x1b[{y + 1};{x + 1}H")
    sys.stdout.flush()


def light_background() -> bool:
    fd = sys.stdin.fileno()
    if not os.isatty(fd):
        return False
    old = termios.tcgetattr(fd)
    reply = b""
    try:
        tty.setraw(fd)
        os.write(sys.stdout.fileno(), b"\x1b]11;?\x1b\\")
        while not reply.endswith((b"\x07", b"\x1b\\")) and select.select([fd], [], [], 0.2)[0]:
            reply += os.read(fd, 64)
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, old)
    if not (m := re.search(rb"rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)", reply)):
        return False
    r, g, b = (int(c[:2], 16) for c in m.groups())
    return 0.299 * r + 0.587 * g + 0.114 * b > 128


def styles(theme: Theme) -> Style:
    if not curses.has_colors():
        return Style()
    curses.start_color()
    curses.use_default_colors()
    if curses.COLORS < 256:
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_RED)
        return Style(flag=curses.color_pair(2), flag_sgr="\x1b[37;41m")
    curses.init_pair(1, -1, theme.header_bg)
    curses.init_pair(2, theme.flag_fg, theme.flag_bg)
    return Style(
        header=curses.A_BOLD | curses.color_pair(1),
        flag=curses.color_pair(2),
        flag_sgr=f"\x1b[38;5;{theme.flag_fg};48;5;{theme.flag_bg}m",
    )


def run(stdscr: curses.window, reviews: Tail, errors: Tail, theme: Theme) -> None:
    curses.curs_set(0)
    style = styles(theme)
    stdscr.timeout(200)
    dirty, show_log = True, False
    reviews.poll()
    herdr.status("idle", "Auto Reviewer")
    while True:
        new = reviews.poll()
        report(new)
        dirty = any([new, errors.poll()]) or dirty
        if dirty:
            draw(stdscr, reviews, errors, show_log, style)
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
        theme = LIGHT if light_background() else DARK
        curses.wrapper(run, Tail(Path(reviews_log), from_start=True), Tail(Path(errors_log)), theme)
    except KeyboardInterrupt:
        pass
    finally:
        herdr.release()


if __name__ == "__main__":
    main()
