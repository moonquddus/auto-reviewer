import curses
import sys
from collections import deque
from pathlib import Path

HISTORY = 1000
TITLE = "Auto Reviewer"
FOOTER = "Press q to exit"


class Tail:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lines: deque[str] = deque(maxlen=HISTORY)
        self.pos = path.stat().st_size if path.exists() else 0
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


def wrap(line: str, width: int) -> list[str]:
    return [line[i : i + width] for i in range(0, len(line), width)] or [""]


def draw_pane(win: curses.window, tail: Tail) -> None:
    win.box()
    h, w = win.getmaxyx()
    win.addnstr(0, 2, f" {tail.path.name} ", w - 4, curses.A_BOLD)
    inner_h, inner_w = h - 2, w - 2
    rows: list[str] = []
    for line in reversed(tail.lines):
        rows[:0] = wrap(line, inner_w)
        if len(rows) >= inner_h:
            break
    for y, row in enumerate(rows[-inner_h:], start=1):
        win.addnstr(y, 1, row, inner_w)
    win.noutrefresh()


def draw(stdscr: curses.window, tails: list[Tail]) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if h < 5 or w < 8 * len(tails):
        stdscr.noutrefresh()
        curses.doupdate()
        return
    stdscr.addnstr(0, max(0, (w - len(TITLE)) // 2), TITLE, w, curses.A_BOLD | curses.A_REVERSE)
    stdscr.addnstr(h - 1, max(0, (w - len(FOOTER)) // 2), FOOTER, w - 1, curses.A_DIM)
    stdscr.noutrefresh()
    pane_w = w // len(tails)
    for i, tail in enumerate(tails):
        width = w - pane_w * i if i == len(tails) - 1 else pane_w
        draw_pane(stdscr.derwin(h - 2, width, 1, pane_w * i), tail)
    curses.doupdate()


def run(stdscr: curses.window, tails: list[Tail]) -> None:
    curses.curs_set(0)
    stdscr.timeout(200)
    dirty = True
    while True:
        dirty = any([t.poll() for t in tails]) or dirty
        if dirty:
            draw(stdscr, tails)
            dirty = False
        key = stdscr.getch()
        if key in (ord("q"), ord("Q")):
            return
        if key == curses.KEY_RESIZE:
            dirty = True


def main() -> None:
    tails = [Tail(Path(p)) for p in sys.argv[1:]]
    try:
        curses.wrapper(run, tails)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
