"""What ster needs from the agent app, without importing its web server.

ster's menus and shortcuts call three things: is an agent usable right now, is a page already running for this
project, and if not, start one and say where it is. Nothing here imports FastAPI or the page's server: the CLI
menu asks this on every redraw, and the page runs in its own process.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from . import runner

HOST = "127.0.0.1"
DEFAULT_PORT = 8780
PORTS = range(
    DEFAULT_PORT, DEFAULT_PORT + 10
)  # one page per project; each takes the first free port here
RECIPES = Path(__file__).parent / "recipes"


@dataclass(frozen=True)
class Launch:
    """The outcome of asking for the page: where it is, whether this call started it, or why it could not be."""

    url: str | None
    started: bool
    error: str | None = None
    pid: int | None = None


def has_usable_agent(env: Mapping[str, str] | None = None, recipes_dir: Path | None = None) -> bool:
    """Whether the page could answer a question now: a command or recipe whose program is installed, or a model
    server with a model that can call tools. *env* is where ASK_AGENT_CMD / ASK_MODEL_URL are read from."""
    env = os.environ if env is None else env
    chosen = runner.select(
        runner.load_recipes(recipes_dir or RECIPES),
        runner.from_env(dict(env)),
        env.get("ASK_RECIPE"),
    )
    return chosen is not None


def _status(port: int, timeout: float = 1.0) -> dict | None:
    """The agent page's own /api/status on *port*, or None when nothing there answers as the page does."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/status", timeout=timeout) as r:
            data = json.load(r)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "root" in data else None


def _same_folder(a: str | Path, b: str | Path) -> bool:
    return Path(a).resolve() == Path(b).resolve()


def find_page(project: Path, ports: range = PORTS, ster_port: int | None = None) -> str | None:
    """The address of a page already running for *project* on this ster, if any.

    A page is one open graph: the ster on a port, with the project folder its history and traces live in. It follows
    whatever that ster serves, so nothing about files is compared. *ster_port* left out means "any".
    """
    for port in ports:
        status = _status(port)
        if not status or not _same_folder(status["root"], project):
            continue
        if ster_port is not None and status.get("ster_port") != ster_port:
            continue
        return f"http://{HOST}:{port}"
    return None


def _in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) == 0


def ensure_running(
    project: Path,
    ster_host: str,
    ster_port: int,
    ports: range = PORTS,
    wait: float = 30.0,
) -> Launch:
    """The page for *project* on this ster: the one already running, or a new one started detached."""
    if url := find_page(project, ports, ster_port):
        return Launch(url, started=False)
    port = next((p for p in ports if not _in_use(p)), None)
    if port is None:
        return Launch(
            None,
            False,
            f"No free port for the agent page between {ports.start} and {ports.stop - 1}.",
        )
    log = project / ".ster" / "agent-app" / "page.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "agent_app",
        "--project",
        str(project),
        "--port",
        str(port),
        "--ster-host",
        ster_host,
        "--ster-port",
        str(ster_port),
    ]
    with open(log, "ab") as out:  # the child keeps its own copy of the handle
        proc = subprocess.Popen(cmd, cwd=project, stdout=out, stderr=out, start_new_session=True)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if (status := _status(port)) and _same_folder(
            status["root"], project
        ):  # ours: it answers on our port
            return Launch(f"http://{HOST}:{port}", started=True, pid=proc.pid)
        if isinstance(code := proc.poll(), int):
            return Launch(None, False, f"The agent page exited with code {code}. Look in {log}.")
        time.sleep(0.2)
    return Launch(None, False, f"The agent page did not answer within {wait:.0f} s. Look in {log}.")
