"""What a plugin needs installed, whether it is, and the exact words for fixing it where ster is running.

A plugin that is switched on but whose package is missing used to vanish without a word: its menu item and its
features simply never appeared. The pieces here let every surface say so, with the command that works in this
environment, and give the in-app installer a way to work where pip does not exist (a ``uv tool`` environment).
"""

from __future__ import annotations

import importlib
import importlib.util
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from .registry import PluginSpec, get


def is_uv_tool_env() -> bool:
    """True when ster runs from a ``uv tool`` environment: it has no pip and is changed with ``uv tool install``."""
    return (Path(sys.prefix) / "uv-receipt.toml").is_file()


def _tool_requirements() -> list[dict]:
    """The requirements ``uv tool install`` recorded for this environment: ster itself first, then each --with."""
    try:
        receipt = tomllib.loads((Path(sys.prefix) / "uv-receipt.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(receipt.get("tool", {}).get("requirements", []))


def install_command(spec: PluginSpec) -> str:
    """The command that adds *spec*'s package to the environment ster is running in.

    In a ``uv tool`` environment it reproduces how ster was installed (an editable checkout stays editable) and keeps
    the packages already added with ``--with``: ``uv tool install --force`` replaces them, it does not add.
    """
    if not is_uv_tool_env():
        return f"pip install 'ster[{spec.extra}]'"
    wanted = spec.dependency.split(">")[0].split("=")[0]
    first, *others = _tool_requirements() or [{"name": "ster"}]
    source = (
        f"--editable {first['editable']}" if first.get("editable") else first.get("name", "ster")
    )
    withs = dict.fromkeys([r["name"] for r in others if r.get("name")] + [wanted])
    return " ".join(["uv tool install --force", source, *(f"--with {name}" for name in withs)])


def missing_dependency(plugin_id: str) -> str | None:
    """Why *plugin_id* cannot run for want of its package, with the command that fixes it; None when it can.

    Nothing is imported unless the package is findable, and a plugin with no installable package has none to miss.
    """
    spec = get(plugin_id)
    if spec is None or not spec.module:
        return None
    deps = importlib.import_module(f"ster.plugins.{spec.id}.deps")
    if deps.is_installed():
        return None
    return f"{spec.name} needs the {spec.module} package, which is not installed. Run: {install_command(spec)}"


def install(requirement: str) -> tuple[bool, str]:
    """Install *requirement* into the interpreter ster runs in; ``(ok, output)``.

    pip is used when this interpreter has it. A ``uv tool`` environment has none, so ``uv pip`` is used there; when
    neither exists the output says so instead of failing in a way nobody sees.
    """
    if importlib.util.find_spec("pip") is not None:
        command = [sys.executable, "-m", "pip", "install", requirement]
    elif uv := shutil.which("uv"):
        command = [uv, "pip", "install", "--python", sys.executable, requirement]
    else:
        return (
            False,
            f"No installer found: this environment has neither pip nor uv. Install {requirement} yourself.",
        )
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    return proc.returncode == 0, proc.stdout + proc.stderr
