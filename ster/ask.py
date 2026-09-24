"""The one place ster asks the user a question on the command line.

Every prompt goes through here rather than calling Rich directly, for two
reasons. It keeps Rich's prompt API behind one adapter, like every other
third-party library in ster. And it gives one answer to "what if nobody is
there?": in CI or any script, stdin is not a terminal, and a prompt would hang
or fail with an EOF traceback. Here it raises :class:`NeedsAnswer` instead —
carrying the question, and how an option can answer it — which the CLI's entry
point turns into one clear line and exit code 2.

With a terminal, behaviour is exactly Rich's: same arguments, same result.
"""

from __future__ import annotations

import sys
from typing import Any

from rich.prompt import Confirm, Prompt
from rich.text import Text


class NeedsAnswer(Exception):
    """A question was reached with no terminal to answer it."""

    def __init__(self, question: str, hint: str | None = None) -> None:
        # Plain text: this ends up in a CI log, where "[cyan]…[/cyan]" is noise.
        self.question = Text.from_markup(question).plain.strip()
        self.hint = hint
        super().__init__(self.question)


def has_terminal() -> bool:
    """Whether someone can type an answer — i.e. stdin is a terminal."""
    return sys.stdin.isatty()


def confirm(question: str, *, hint: str | None = None, **rich_kwargs: Any) -> bool:
    """Ask a yes/no *question*; *hint* says which option answers it in a script."""
    if not has_terminal():
        raise NeedsAnswer(question, hint)
    return Confirm.ask(question, **rich_kwargs)


def text(question: str, *, hint: str | None = None, **rich_kwargs: Any) -> str:
    """Ask for a line of text; *hint* says which option answers it in a script."""
    if not has_terminal():
        raise NeedsAnswer(question, hint)
    return Prompt.ask(question, **rich_kwargs)
