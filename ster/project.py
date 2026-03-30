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

def _git_root(cwd: Path) -> Path | None:
    """Return the git root for *cwd*, or None if not inside a repository."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd), capture_output=True, text=True,
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

    root: Path                          # git root or CWD
    files: list[Path] = field(default_factory=list)  # paths relative to *root*
    lang: str = "en"

    # ── class-level path helpers ──────────────────────────────────────────────

    @staticmethod
    def _ster_dir(cwd: Path) -> Path:
        root = _git_root(cwd) or cwd
        return root / ".ster"

    @staticmethod
    def _project_file(cwd: Path) -> Path:
        return Project._ster_dir(cwd) / "project.json"

    # ── persistence ───────────────────────────────────────────────────────────

    @staticmethod
    def load(cwd: Path) -> "Project | None":
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
            )
        except Exception:
            return None

    def save(self) -> None:
        """Write the project file, creating .ster/ if needed."""
        ster_dir = self.root / ".ster"
        ster_dir.mkdir(parents=True, exist_ok=True)
        p = ster_dir / "project.json"
        data = {
            "files": [str(f) for f in self.files],
            "lang": self.lang,
        }
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

    def add_file(self, path: Path) -> None:
        """Add *path* to the project (stored relative to root)."""
        try:
            rel = path.resolve().relative_to(self.root.resolve())
        except ValueError:
            rel = path.resolve()   # not under root — store absolute
        if rel not in self.files:
            self.files.append(rel)

    def remove_file(self, path: Path) -> None:
        try:
            rel = path.resolve().relative_to(self.root.resolve())
        except ValueError:
            rel = path.resolve()
        self.files = [f for f in self.files if f != rel]

    def set_lang(self, lang: str) -> None:
        self.lang = lang
        self.save()
