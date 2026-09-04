"""Git edit-activity statistics for a taxonomy file, independent of GitManager."""

from __future__ import annotations

from pathlib import Path

from . import _subprocess


def file_activity(path: Path) -> dict | None:
    """Git edit activity for *path*: ``{last, total, last_month}`` or None.

    ``last`` is the ISO date of the most recent commit touching the file, ``total``
    the number of commits, ``last_month`` how many of those fall in the last 30 days.
    Returns None when git is unavailable or the file isn't tracked.
    """
    from datetime import UTC, datetime, timedelta

    if not _subprocess._git_available():
        return None
    proc = _subprocess._git("log", "--follow", "--format=%cI", "--", path.name, cwd=path.parent)
    dates = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode != 0 or not dates:
        return None
    cutoff = datetime.now(UTC) - timedelta(days=30)
    last_month = sum(1 for d in dates if datetime.fromisoformat(d) >= cutoff)
    return {"last": dates[0][:10], "total": len(dates), "last_month": last_month}
