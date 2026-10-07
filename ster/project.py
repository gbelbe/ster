"""Project file management — .ster/project.json tied to the git root.

A Project records which taxonomy files belong to the current editing session
and stores display preferences (language).  The project file is the only
ster-managed file in the repository; all taxonomy data stays in the .ttl files.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# ──────────────────────────── git helpers ────────────────────────────────────


STER_DIR = ".ster"  # a project's state folder, beside its files
PROJECT_FILE = "project.json"  # what marks a folder as a ster project


def home_of(file: Path) -> Path:
    """The folder a file's project keeps its ``.ster/`` in: the nearest parent that already has a ``project.json``
    there, else the file's own folder. Query traces and the Talk to graph page's history live in that folder, so
    a file in ``data/`` of a project whose ``.ster/`` is one level up still shares it."""
    here = file.resolve().parent
    for folder in (here, *here.parents):
        if (folder / STER_DIR / PROJECT_FILE).is_file():
            return folder
    return here


def _git_root(cwd: Path) -> Path | None:
    """Return the git root for *cwd*, or None if not inside a repository."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            return Path(r.stdout.strip())
    except Exception:
        pass
    return None


# ──────────────────────────── Project ────────────────────────────────────────


@dataclass
class Project:
    """Persistent session settings tied to a git repository (or directory)."""

    root: Path  # git root or CWD
    files: list[Path] = field(default_factory=list)  # paths relative to *root*
    lang: str = "en"
    # Whether to offer RDF files one level down. None until the user answers,
    # which is what lets ster ask exactly once.
    include_subfolders: bool | None = None
    # The read-only context last chosen for each editable file, all relative to
    # *root*: ``{"gear.ttl": ["vocab/labels.ttl"]}``. Offered pre-ticked.
    context: dict[str, list[str]] = field(default_factory=dict)

    # ── class-level path helpers ──────────────────────────────────────────────

    @staticmethod
    def _ster_dir(cwd: Path) -> Path:
        root = _git_root(cwd) or cwd
        return root / STER_DIR

    @staticmethod
    def _project_file(cwd: Path) -> Path:
        return Project._ster_dir(cwd) / PROJECT_FILE

    # ── persistence ───────────────────────────────────────────────────────────

    @staticmethod
    def load(cwd: Path) -> Project | None:
        """Load the project file for *cwd*, or return None if none exists."""
        p = Project._project_file(cwd)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            root = _git_root(cwd) or cwd
            return Project(
                root=root,
                files=[Path(f) for f in data.get("files", [])],
                lang=data.get("lang", "en"),
                include_subfolders=data.get("include_subfolders"),
                context=dict(data.get("context", {})),
            )
        except Exception:
            return None

    def save(self) -> None:
        """Write the project file, creating .ster/ if needed."""
        ster_dir = self.root / STER_DIR
        ster_dir.mkdir(parents=True, exist_ok=True)
        p = ster_dir / PROJECT_FILE
        data: dict[str, object] = {
            "files": [str(f) for f in self.files],
            "lang": self.lang,
        }
        if self.include_subfolders is not None:
            data["include_subfolders"] = self.include_subfolders
        if self.context:
            data["context"] = self.context
        p.write_text(json.dumps(data, indent=2))

    # ── file list helpers ─────────────────────────────────────────────────────

    def resolved_files(self) -> list[Path]:
        """Return absolute paths for project files that actually exist on disk."""
        result: list[Path] = []
        for f in self.files:
            abs_f = f if f.is_absolute() else self.root / f
            if abs_f.exists():
                result.append(abs_f)
        return result

    def _relative(self, path: Path) -> Path:
        """*path* relative to root, or absolute when it lies outside it."""
        try:
            return path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return path.resolve()

    def add_file(self, path: Path) -> None:
        """Add *path* to the project (stored relative to root)."""
        rel = self._relative(path)
        if rel not in self.files:
            self.files.append(rel)

    def remove_file(self, path: Path) -> None:
        rel = self._relative(path)
        self.files = [f for f in self.files if f != rel]

    # ── remembered context ────────────────────────────────────────────────────

    def forget_choices(self) -> None:
        """Forget the subfolder answer and every remembered context, so both are asked again."""
        self.include_subfolders = None
        self.context = {}

    def remember_context(self, editable: Path, chosen: list[Path]) -> None:
        """Record *chosen* as the read-only context last loaded beside *editable*."""
        self.context[str(self._relative(editable))] = [str(self._relative(p)) for p in chosen]

    def remembered_context(self, editable: Path) -> list[Path]:
        """The context last chosen for *editable*, minus files that no longer exist."""
        stored = self.context.get(str(self._relative(editable)), [])
        paths = [self.root / name for name in stored]
        return [path for path in paths if path.exists()]

    def set_lang(self, lang: str) -> None:
        self.lang = lang
        self.save()
