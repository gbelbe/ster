"""The start command: ``python -m agent_app [--project DIR] [--port N] [--ster-host H] [--ster-port N]``."""

from __future__ import annotations

import argparse
import os
import threading
from collections.abc import Sequence


def parse(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agent_app", description="Talk to a ster project's graph in plain language."
    )
    p.add_argument("--project", help="the ster project folder (default: the current folder)")
    p.add_argument("--port", type=int, help="port of the page (default 8780)")
    p.add_argument("--ster-host", help="where ster listens (default 127.0.0.1)")
    p.add_argument("--ster-port", type=int, help="where ster listens or is started (default 8765)")
    return p.parse_args(argv)


def apply(args: argparse.Namespace, env: dict[str, str]) -> None:
    """Command-line options become the ASK_* settings the server reads when it is imported."""
    for value, name in (
        (args.project, "ASK_PROJECT"),
        (args.port, "ASK_PORT"),
        (args.ster_host, "ASK_STER_HOST"),
        (args.ster_port, "ASK_STER_PORT"),
    ):
        if value is not None:
            env[name] = str(value)


def _warm_ster(server) -> None:
    """Start the project's ster in the background; a folder that is not a ster project just leaves the header red."""
    try:
        server.ensure_ster()
    except (OSError, ValueError, KeyError) as exc:
        print(f"ster was not started: {exc}")


def main(argv: Sequence[str] | None = None) -> int:
    apply(parse(argv), os.environ)  # type: ignore[arg-type]
    import uvicorn

    from . import server  # read the settings above, so imported only now

    # so the header is green on opening instead of after the first question
    threading.Thread(target=_warm_ster, args=(server,), daemon=True).start()
    print(f"Agent page: http://127.0.0.1:{server.WEB_PORT}   (project: {server.ROOT})")
    uvicorn.run(server.app, host="127.0.0.1", port=server.WEB_PORT, log_level="warning")
    return 0
