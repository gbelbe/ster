"""Examples for every command's --help, and the scripting notes for ``ster --help``.

Kept in one registry rather than scattered through thirteen docstrings: an
example is what someone copies into a script, so the set is easier to keep
correct in one place, and a command added without examples fails a test.
Commands whose docstring already carries an Examples section (export, convert,
subclass) keep it and are not listed here.
"""

from __future__ import annotations

from typing import Final

import typer

from ._exit import EXIT_CODES_HELP

# Command name → example lines. Each line is a complete, runnable command.
EXAMPLES: Final[dict[str, list[str]]] = {
    "show": [
        "ster show gear.ttl                      # open the interactive browser",
        "ster show gear.ttl --plain              # print the tree and exit (scripts)",
        "ster show gear.ttl -x vocab/labels.ttl  # with a read-only context file",
    ],
    "add": [
        'ster add "Tent" --en Tent --fr Tente --file gear.ttl',
        'ster add "Dome tent" --parent TEN --en "Dome tent" --file gear.ttl',
    ],
    "remove": [
        "ster remove TEN --yes --file gear.ttl            # no confirmation (scripts)",
        "ster remove TEN --cascade --yes --file gear.ttl  # with its descendants",
    ],
    "move": [
        "ster move DOM --parent SHE --file gear.ttl  # new parent",
        "ster move DOM --file gear.ttl               # promote to the top level",
    ],
    "label": [
        'ster label TEN fr "Tente" --file gear.ttl',
        'ster label TEN en "Shelter" --alt --file gear.ttl  # alternative label',
    ],
    "define": [
        'ster define TEN en "A portable shelter." --file gear.ttl',
    ],
    "relate": [
        "ster relate TEN TAR --file gear.ttl           # add skos:related",
        "ster relate TEN TAR --remove --file gear.ttl  # remove it",
    ],
    "rename": [
        "ster rename TEN Tents --file gear.ttl  # new URI; cross-references follow",
    ],
    "handles": [
        "ster handles --file gear.ttl",
        "ster handles --lang fr --file gear.ttl",
    ],
    "validate": [
        "ster validate --file gear.ttl  # exit 0 if clean, 1 if issues were found",
        "ster validate --file gear.ttl || echo 'fix the issues above'",
    ],
    "init-ci": [
        "ster init-ci            # scaffold .github/workflows/taxonomy-ci.yml here",
        "ster init-ci --force    # overwrite existing files",
    ],
    "serve": [
        "ster serve gear.ttl --port 8080",
        "ster serve gear.ttl -x vocab/labels.ttl",
    ],
    "publish": [
        "ster publish gear.ttl --bump minor         # stable release",
        "ster publish gear.ttl --channel dev --no-open",
    ],
}

SCRIPTING_HELP: Final = f"""\
[bold]Scripting & CI[/bold]
  With no terminal (CI, cron, a pipe) ster never asks a question: it stops with
  exit 2 and names the option that answers it. Pass everything explicitly:
    ster validate --file vocab/gear.ttl
    ster export --file vocab/gear.ttl --output site/ --no-open

{EXIT_CODES_HELP}"""


def _epilog(lines: list[str]) -> str:
    # Blank-line separated: Rich's help formatter folds single newlines.
    return "[bold]Examples[/bold]\n\n" + "\n\n".join(f"  {line}" for line in lines)


def attach_examples(app: typer.Typer) -> None:
    """Give each command in EXAMPLES its epilog, and the app its scripting notes.

    Idempotent: the epilog is set, not appended, so calling it twice is safe.
    """
    for command in app.registered_commands:
        lines = EXAMPLES.get(command.name or "")
        if lines:
            command.epilog = _epilog(lines)
    app.info.epilog = SCRIPTING_HELP.replace("\n", "\n\n")
