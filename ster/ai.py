"""Thin wrapper around the `llm` library for ster AI features.

Usage in any ster feature:

    from .ai import is_available, is_configured, get_model_for, suggest_concept_names

All public functions degrade gracefully when `llm` is not installed.
Configuration is stored in ~/.config/ster/ai.json.

Copy-paste mode
---------------
When copypaste mode is active, no LLM call is made.  Instead the rendered
prompt is displayed in the terminal (and copied to the clipboard when
possible), and the user pastes the model's response back.

Configure via the main menu → Configure AI → Copy-paste option.
Enable for one run:    STER_COPYPASTE=1 ster <command>
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from . import prompts as _P

# ── Config helpers ─────────────────────────────────────────────────────────────

_CONFIG_PATH = Path.home() / ".config" / "ster" / "ai.json"


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except Exception:
        return {}


def _save_config(cfg: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def get_config() -> dict:
    """Return persisted AI config (may be empty)."""
    return _load_config()


def save_model(model_id: str) -> None:
    """Persist the chosen default model ID."""
    cfg = _load_config()
    cfg["model"] = model_id
    _save_config(cfg)


def save_model_for(task: str, model_id: str) -> None:
    """Persist a per-task model override."""
    cfg = _load_config()
    cfg.setdefault("models", {})[task] = model_id
    _save_config(cfg)


def get_saved_model() -> str | None:
    """Return the saved default model ID, or None."""
    return _load_config().get("model")


# ── Copy-paste mode ────────────────────────────────────────────────────────────


def is_copypaste() -> bool:
    """True when copy-paste mode is active.

    Precedence: STER_COPYPASTE env var  >  ai.json "copypaste" key.
    """
    env = os.environ.get("STER_COPYPASTE")
    if env is not None:
        return env.lower() in ("1", "true", "yes")
    return bool(_load_config().get("copypaste", False))


def save_copypaste(enabled: bool) -> None:
    """Persist copy-paste mode to ai.json."""
    cfg = _load_config()
    cfg["copypaste"] = enabled
    _save_config(cfg)


def _try_copy_to_clipboard(text: str) -> bool:
    """Copy *text* to the system clipboard. Returns True on success."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            return True
        if sys.platform.startswith("linux"):
            for cmd in [
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ]:
                try:
                    subprocess.run(cmd, input=text.encode(), check=True)
                    return True
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
        if sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode(), check=True)
            return True
    except Exception:
        pass
    return False


def _copypaste_interact(prompt_text: str) -> str:
    """Display *prompt_text* in a panel, copy it to the clipboard, then collect
    the user's pasted response (terminated by a blank line)."""
    from rich.console import Console
    from rich.panel import Panel

    con = Console()

    copied = _try_copy_to_clipboard(prompt_text)
    title = (
        "[bold cyan]PROMPT — copied to clipboard[/bold cyan]"
        if copied
        else "[bold cyan]PROMPT[/bold cyan]"
    )

    con.print()
    con.print(Panel(prompt_text, title=title, border_style="cyan", padding=(1, 2)))
    con.print()
    con.print(
        "[dim]Paste the model's response below.\n"
        "Press [bold]Enter[/bold] on an empty line when done.[/dim]\n"
    )

    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            break
        lines.append(line)

    return "\n".join(lines)


# ── Availability checks ────────────────────────────────────────────────────────


def is_available() -> bool:
    """True if the `llm` package is installed."""
    try:
        import llm  # noqa: F401

        return True
    except ImportError:
        return False


def is_configured() -> bool:
    """True if a model has been saved OR copy-paste mode is active."""
    return is_copypaste() or (is_available() and bool(get_saved_model()))


# ── Model discovery ────────────────────────────────────────────────────────────

_MODULE_DISPLAY: dict[str, str] = {
    "llm": "OpenAI",
    "llm_anthropic": "Anthropic  (Claude)",
    "llm_gemini": "Google  (Gemini)",
    "llm_mistral": "Mistral AI",
    "llm_groq": "Groq",
    "llm_ollama": "Ollama  (local)",
    "llm_gpt4all": "GPT4All  (local)",
    "llm_llamafile": "llamafile  (local)",
    "llm_mlx": "MLX  (Apple Silicon)",
    "llm_bedrock": "Amazon Bedrock",
    "llm_vertex": "Google Vertex AI",
    "llm_cohere": "Cohere",
    "llm_together": "Together AI",
    "llm_replicate": "Replicate",
    "llm_openrouter": "OpenRouter",
}

_KNOWN_PLUGIN_DEFS: list[tuple[str, str, str]] = [
    ("llm_anthropic", "Anthropic  (Claude)", "llm-anthropic"),
    ("llm_gemini", "Google  (Gemini)", "llm-gemini"),
    ("llm_mistral", "Mistral AI", "llm-mistral"),
    ("llm_groq", "Groq", "llm-groq"),
    ("llm_cohere", "Cohere", "llm-cohere"),
    ("llm_together", "Together AI", "llm-together"),
    ("llm_openrouter", "OpenRouter", "llm-openrouter"),
    ("llm_bedrock", "Amazon Bedrock", "llm-bedrock"),
    ("llm_vertex", "Google Vertex AI", "llm-vertex"),
    ("llm_ollama", "Ollama  (local)", "llm-ollama"),
    ("llm_gpt4all", "GPT4All  (local)", "llm-gpt4all"),
    ("llm_llamafile", "llamafile  (local)", "llm-llamafile"),
    ("llm_mlx", "MLX  (Apple Silicon)", "llm-mlx"),
]


def available_plugins(installed_module_ids: set[str]) -> list[tuple[str, str, str]]:
    """Return (module_id, display_name, pip_package) for known plugins not yet installed."""
    return [
        (mid, lbl, pkg) for mid, lbl, pkg in _KNOWN_PLUGIN_DEFS if mid not in installed_module_ids
    ]


ProviderEntry = tuple[str, str, list[tuple[str, str]]]


def discover_models() -> tuple[list[ProviderEntry], list[ProviderEntry]]:
    """Return (online_providers, offline_providers) discovered live from llm.get_models()."""
    if not is_available():
        return [], []

    online: dict[str, tuple[str, list[tuple[str, str]]]] = {}
    offline: dict[str, tuple[str, list[tuple[str, str]]]] = {}

    try:
        import llm

        llm._loaded = False  # type: ignore[attr-defined]
        for m in llm.get_models():
            module = type(m).__module__.split(".")[0]
            needs_key = bool(getattr(m, "needs_key", False))
            label = _MODULE_DISPLAY.get(
                module,
                module.replace("llm_", "").replace("_", " ").title(),
            )
            bucket = online if needs_key else offline
            if module not in bucket:
                bucket[module] = (label, [])
            bucket[module][1].append((m.model_id, m.model_id))
    except Exception:
        pass

    def _to_list(bucket: dict) -> list[ProviderEntry]:
        return [(mid, lbl, models) for mid, (lbl, models) in sorted(bucket.items())]

    return _to_list(online), _to_list(offline)


def model_needs_key(model_id: str) -> str | None:
    """Return the key alias needed by model_id, or None if no key required."""
    if not is_available():
        return None
    try:
        import llm

        model = llm.get_model(model_id)
        if getattr(model, "needs_key", False):
            return getattr(model, "key", None) or model_id
        return None
    except Exception:
        return None


def save_key(key_name: str, key_value: str) -> None:
    """Persist an API key into llm's key store."""
    try:
        import llm

        keys_path = llm.user_dir() / "keys.json"
        try:
            current: dict = json.loads(keys_path.read_text())
        except Exception:
            current = {}
        current[key_name] = key_value
        keys_path.parent.mkdir(parents=True, exist_ok=True)
        keys_path.write_text(json.dumps(current, indent=2))
    except Exception:
        pass


# ── Model resolution ───────────────────────────────────────────────────────────


def get_model_for(task: str):
    """Return the configured llm.Model for *task*, or raise RuntimeError.

    Lookup order:
      1. Per-task override in ai.json  "models": { "<task>": "<model_id>" }
      2. Global default  ai.json  "model"
    """
    if not is_available():
        raise RuntimeError("The 'llm' package is not installed. Run: uv pip install 'ster[ai]'")
    cfg = _load_config()
    model_id = cfg.get("models", {}).get(task) or cfg.get("model")
    if not model_id:
        raise RuntimeError("No LLM model configured. Press 'L' in detail view to set one up.")
    import llm

    try:
        return llm.get_model(model_id)
    except Exception as exc:
        raise RuntimeError(f"Could not load model '{model_id}': {exc}") from exc


# Keep the old name as an alias for backward compatibility.
def get_model():
    """Return the default configured llm.Model, or raise RuntimeError."""
    return get_model_for("default")


# ── Response helpers ───────────────────────────────────────────────────────────

_PREAMBLE_RE = re.compile(
    r"^(sure|here|below|following|certainly|of course|these|the following)",
    re.IGNORECASE,
)
_NUMBERING_RE = re.compile(r"^[\d]+[.)]\s*|^[-*•]\s*")


def _is_label(line: str) -> bool:
    s = line.strip().strip('"').strip("'")
    if not s:
        return False
    if s.endswith(":"):
        return False
    if len(s) > 80:
        return False
    return not _PREAMBLE_RE.match(s)


@contextmanager
def _safe_stderr():
    """Redirect stderr to /dev/null to suppress llm plugin noise inside curses."""
    old = sys.stderr
    try:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115
        yield
    finally:
        try:
            sys.stderr.close()
        except Exception:
            pass
        sys.stderr = old


def _call(prompt_text: str, task: str) -> str:
    """Run *prompt_text* through the configured model (or copy-paste mode).

    Returns the raw response text.
    """
    if is_copypaste():
        return _copypaste_interact(prompt_text)
    model = get_model_for(task)
    with _safe_stderr():
        return model.prompt(prompt_text).text().strip()


# ── Feature: suggest concept names (add-concept wizard) ───────────────────────


def _build_concept_names_prompt(
    taxonomy_name: str,
    taxonomy_description: str,
    parent_label: str | None,
    lang: str,
    n: int,
    exclude: list[str] | None,
) -> str:
    """Return the rendered prompt for suggest_concept_names without calling the LLM."""
    ex = exclude or []
    ex_hint = (
        f"Do NOT repeat any of these already-proposed labels: {', '.join(ex[:60])}" if ex else ""
    )
    desc_line = f"Description: {taxonomy_description}\n" if taxonomy_description.strip() else ""
    if parent_label:
        parent_line = f'Parent concept: "{parent_label}"\n'
        scope_phrase = f'narrower concept labels directly under "{parent_label}"'
    else:
        parent_line = "Scope: top-level concepts (direct children of the scheme)\n"
        scope_phrase = "top-level concept labels for this taxonomy"

    return _P.TMPL_SUGGEST_CONCEPT_NAMES.substitute(
        taxonomy_name=taxonomy_name,
        taxonomy_description_line=desc_line,
        parent_line=parent_line,
        scope_phrase=scope_phrase,
        lang=lang,
        n=n,
        exclude_hint=ex_hint,
    )


def render_suggest_concept_names_prompt(
    taxonomy_name: str,
    taxonomy_description: str,
    parent_label: str | None,
    lang: str,
    n: int = 20,
    exclude: list[str] | None = None,
) -> str:
    """Return the rendered prompt text without calling the LLM.

    Used by the prompt-review step so the user can inspect the prompt
    before it is submitted.
    """
    return _build_concept_names_prompt(
        taxonomy_name, taxonomy_description, parent_label, lang, n, exclude
    )


def suggest_concept_names(
    taxonomy_name: str,
    taxonomy_description: str,
    parent_label: str | None,
    lang: str,
    n: int = 20,
    exclude: list[str] | None = None,
) -> list[str]:
    """Return up to *n* concept name suggestions for insertion into a taxonomy.

    Works for both top-level concepts (parent_label=None) and narrower
    concepts (parent_label="<pref label of parent>").
    """
    ex = exclude or []
    prompt_text = _build_concept_names_prompt(
        taxonomy_name, taxonomy_description, parent_label, lang, n, ex
    )
    text = _call(prompt_text, _P.SUGGEST_CONCEPT_NAMES)

    def _clean(ln: str) -> str:
        return _NUMBERING_RE.sub("", ln.strip()).strip().strip('"').strip("'")

    results = [
        _clean(ln) for ln in text.splitlines() if _is_label(_NUMBERING_RE.sub("", ln.strip()))
    ]
    seen_set = {e.lower() for e in ex}
    return [r for r in results if r.lower() not in seen_set][:n]


# ── Feature: suggest alternative labels ───────────────────────────────────────


def suggest_alt_labels(
    pref_label: str,
    taxonomy_name: str,
    taxonomy_description: str,
    lang: str,
) -> list[str]:
    """Return up to 5 alternative-label suggestions for a concept."""
    desc_line = f"Description: {taxonomy_description}\n" if taxonomy_description.strip() else ""
    prompt_text = _P.TMPL_SUGGEST_ALT_LABELS.substitute(
        taxonomy_name=taxonomy_name,
        taxonomy_description_line=desc_line,
        pref_label=pref_label,
        lang=lang,
    )
    text = _call(prompt_text, _P.SUGGEST_ALT_LABELS)

    def _clean(ln: str) -> str:
        return _NUMBERING_RE.sub("", ln.strip()).strip().strip('"').strip("'")

    return [_clean(ln) for ln in text.splitlines() if _is_label(_NUMBERING_RE.sub("", ln.strip()))][
        :5
    ]


# ── Feature: suggest definition ───────────────────────────────────────────────


def suggest_definition(
    pref_label: str,
    taxonomy_name: str,
    taxonomy_description: str,
    parent_label: str | None,
    lang: str,
) -> str:
    """Return an AI-suggested skos:definition for a concept."""
    desc_line = f"Description: {taxonomy_description}\n" if taxonomy_description.strip() else ""
    if parent_label:
        parent_line = f'Parent concept: "{parent_label}"\n'
    else:
        parent_line = "Scope: top-level concept\n"
    prompt_text = _P.TMPL_SUGGEST_DEFINITION.substitute(
        taxonomy_name=taxonomy_name,
        taxonomy_description_line=desc_line,
        parent_line=parent_line,
        pref_label=pref_label,
        lang=lang,
    )
    return _call(prompt_text, _P.SUGGEST_DEFINITION).strip()
