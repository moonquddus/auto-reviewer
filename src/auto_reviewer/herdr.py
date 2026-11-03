import os
import subprocess
import time

SOURCE = "auto-reviewer"


def enabled() -> bool:
    return os.environ.get("HERDR_ENV") == "1" and all(map(os.environ.get, ("HERDR_BIN_PATH", "HERDR_PANE_ID")))


def call(*args: str) -> None:
    if not enabled():
        return
    try:
        subprocess.run([os.environ["HERDR_BIN_PATH"], *args], capture_output=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        pass


def pane(command: str, *args: str) -> None:
    call("pane", command, os.environ.get("HERDR_PANE_ID", ""), "--source", SOURCE, *args, "--seq", str(time.time_ns() // 1000))


def status(state: str, text: str) -> None:
    pane("report-agent", "--agent", SOURCE, "--state", state)
    pane("report-metadata", "--display-agent", text)


def notify(title: str, body: str) -> None:
    call("notification", "show", title, "--body", body, "--sound", "done")


def release() -> None:
    pane("release-agent", "--agent", SOURCE)
