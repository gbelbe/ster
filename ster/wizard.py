"""Interactive first-time setup wizard for creating a new taxonomy."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.rule import Rule
from rich.table import Table
from rich import box

console = Console()

_STEP_STYLE = "bold cyan"
_OPT_HINT = "[dim](optional — press Enter to skip)[/dim]"
_KNOWN_LANGS = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "it": "Italian",
    "nl": "Dutch",
    "pt": "Portuguese",
}


@dataclass
class SetupResult:
    file_path: Path
    base_uri: str
    languages: list[str]
    titles: dict[str, str] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)
    creator: str = ""
    created: str = ""


def run(default_path: Path | None = None) -> SetupResult | None:
    """Run the interactive setup wizard. Returns None if the user aborts."""
    _welcome()

    steps = [
        _step_file,
        _step_languages,
        _step_title,
        _step_description,
        _step_base_uri,
        _step_creator,
        _step_confirm,
    ]

    ctx: dict = {"file_path": default_path}

    for idx, step_fn in enumerate(steps[:-1], start=1):
        _header(idx, len(steps) - 1, step_fn.__doc__ or "")
        result = step_fn(ctx)
        if result is False:          # user typed 'quit'
            console.print("[yellow]Setup cancelled.[/yellow]")
            return None

    # Final confirmation step
    _header(len(steps) - 1, len(steps) - 1, _step_confirm.__doc__ or "")
    confirmed = _step_confirm(ctx)
    if not confirmed:
        console.print("[yellow]Setup cancelled.[/yellow]")
        return None

    return SetupResult(
        file_path=ctx["file_path"],
        base_uri=ctx["base_uri"],
        languages=ctx["languages"],
        titles=ctx.get("titles", {}),
        descriptions=ctx.get("descriptions", {}),
        creator=ctx.get("creator", ""),
        created=str(date.today()),
    )


# ──────────────────────────── welcome ────────────────────────────────────────

_ASCII = """\
[bold cyan]     _
    | |
 ___| |_ ___ _ __
/ __| __/ _ \\ '__|\n \\__ \\ ||  __/ |
|___/\\__\\___|_|[/bold cyan]

[dim]  [ Breton: "Meaning" or "Sense" ]
  [  Druidic Knowledge Command   ][/dim]"""


def _welcome() -> None:
    console.print()
    console.print(Panel(
        _ASCII + "\n\n"
        "This wizard will create a new taxonomy file step by step.\n"
        "  • Press [bold]Enter[/bold] to accept the suggested default.\n"
        "  • Type [bold]skip[/bold] on any optional field to move on.\n"
        "  • Type [bold]quit[/bold] at any prompt to cancel.",
        border_style="cyan",
        padding=(1, 4),
    ))


# ──────────────────────────── step helpers ───────────────────────────────────

def _header(step: int, total: int, title: str) -> None:
    console.print()
    console.print(Rule(f"[{_STEP_STYLE}]Step {step}/{total} — {title}[/{_STEP_STYLE}]"))


def _ask(prompt: str, default: str = "", optional: bool = False) -> str | None:
    """Prompt the user. Returns None on 'quit', '' on skip/empty."""
    hint = f"  {_OPT_HINT}" if optional else ""
    full_prompt = f"[cyan]{prompt}[/cyan]{hint}"
    val = Prompt.ask(full_prompt, default=default, console=console)
    if val.strip().lower() == "quit":
        return None
    if val.strip().lower() == "skip":
        return ""
    return val.strip()


# ──────────────────────────── steps ──────────────────────────────────────────

def _step_file(ctx: dict) -> bool:
    """Output file"""
    suggestion = str(ctx.get("file_path") or "taxonomy.ttl")
    val = _ask("File path for the new taxonomy", default=suggestion)
    if val is None:
        return False
    if not val:
        val = suggestion
    path = Path(val)
    if not path.suffix:
        path = path.with_suffix(".ttl")
    ctx["file_path"] = path
    return True


def _step_languages(ctx: dict) -> bool:
    """Languages"""
    console.print(
        "  Supported: [dim]" +
        ", ".join(f"{k} ({v})" for k, v in _KNOWN_LANGS.items()) +
        "[/dim]"
    )
    val = _ask("Languages to include (comma-separated)", default="en,fr")
    if val is None:
        return False
    langs = [lg.strip().lower() for lg in (val or "en,fr").split(",") if lg.strip()]
    if not langs:
        langs = ["en"]
    ctx["languages"] = langs
    return True


def _step_title(ctx: dict) -> bool:
    """Taxonomy name"""
    langs: list[str] = ctx["languages"]
    titles: dict[str, str] = {}
    for i, lang in enumerate(langs):
        required = i == 0
        lang_name = _KNOWN_LANGS.get(lang, lang)
        prompt = f"Title [{lang} — {lang_name}]"
        val = _ask(prompt, optional=not required)
        if val is None:
            return False
        if val:
            titles[lang] = val
        elif required:
            console.print(f"  [yellow]A title in {lang!r} is required.[/yellow]")
            val = _ask(prompt)
            if val is None:
                return False
            titles[lang] = val or f"Unnamed Taxonomy"
    ctx["titles"] = titles
    return True


def _step_description(ctx: dict) -> bool:
    """Short description"""
    langs: list[str] = ctx["languages"]
    descriptions: dict[str, str] = {}
    for lang in langs:
        lang_name = _KNOWN_LANGS.get(lang, lang)
        val = _ask(f"Description [{lang} — {lang_name}]", optional=True)
        if val is None:
            return False
        if val:
            descriptions[lang] = val
    ctx["descriptions"] = descriptions
    return True


def _step_base_uri(ctx: dict) -> bool:
    """Base URI (namespace)"""
    # Suggest a URI derived from the file stem
    stem = Path(ctx.get("file_path", "taxonomy")).stem.lower().replace(" ", "-")
    suggestion = f"https://example.org/{stem}/"
    console.print(
        "  The base URI is the namespace prefix for all concept URIs.\n"
        "  Example: [dim]https://myorg.org/taxonomy/[/dim]"
    )
    val = _ask("Base URI", default=suggestion)
    if val is None:
        return False
    uri = val or suggestion
    if not uri.endswith(("/", "#")):
        uri += "/"
    ctx["base_uri"] = uri
    return True


def _step_creator(ctx: dict) -> bool:
    """Creator / author"""
    val = _ask("Author or organisation name", optional=True)
    if val is None:
        return False
    ctx["creator"] = val
    return True


def _step_confirm(ctx: dict) -> bool:
    """Summary & confirmation"""
    table = Table(box=box.ROUNDED, show_header=False, border_style="cyan", padding=(0, 2))
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("File", str(ctx.get("file_path", "")))
    table.add_row("Base URI", ctx.get("base_uri", ""))
    table.add_row("Languages", ", ".join(ctx.get("languages", [])))

    for lang, title in ctx.get("titles", {}).items():
        table.add_row(f"Title [{lang}]", title)
    for lang, desc in ctx.get("descriptions", {}).items():
        table.add_row(f"Description [{lang}]", desc)
    if ctx.get("creator"):
        table.add_row("Creator", ctx["creator"])
    table.add_row("Created", str(date.today()))

    console.print()
    console.print(table)
    console.print()
    return Confirm.ask("[cyan]Create this taxonomy?[/cyan]", default=True, console=console)
