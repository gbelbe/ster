"""The exit codes ster promises to scripts and CI, defined once.

A CI step has to tell "the ontology has issues" from "the path is wrong" from
"ster crashed" — they need different fixes, and only the first means the build
should fail on the content. So every failure picks one of these instead of the
blanket ``1`` it used to exit with.
"""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    PROBLEMS = 1  # the command ran and found problems (validate, publish pre-flight)
    USAGE = 2  # bad option or argument, unknown concept, or a question with no terminal
    FILE = 3  # file missing, unreadable, or could not be saved
    INVALID_RDF = 4  # not valid RDF, or nothing ster can model
    UNEXPECTED = 5  # not the input's fault: a bug or a broken install


EXIT_CODES_HELP = """\
[bold]Exit codes[/bold] (for scripts and CI):
  0  success
  1  problems found (e.g. [cyan]validate[/cyan] reported issues)
  2  wrong usage — bad option, unknown concept, or a question with no terminal to ask
  3  file missing, unreadable, or could not be saved
  4  not valid RDF, or nothing ster can model
  5  unexpected error — run again with [cyan]STER_DEBUG=1[/cyan] for the traceback"""
