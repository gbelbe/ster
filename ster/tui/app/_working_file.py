"""Changing which of the open files is the writable one, from the editor.

The decision and its ordering live in :mod:`ster.working_file`; this mixin
supplies the three side effects that module injects — flush, load, apply — and
owns only what is genuinely Textual about the operation: running the parse off
the UI thread, and repainting what the new roles changed.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Final

from ster.working_file import WorkingFileError, switch

from ..working_file_chip import WorkingFileChip, WorkingFileMenu
from ._constants import _READ_ONLY_MESSAGE
from ._state import _AppState

_LIT_WARNING: Final = "warning"
_LIT_WORKING_FILE: Final = "Working file"  # the notification title, shared by all three paths


class _WorkingFileMixin(_AppState):
    """Mixin: the header's working-file chip, its drop-down menu, and the
    reload that swapping the writable file costs."""

    # ── what the control shows ────────────────────────────────────────────────

    def loaded_files(self) -> list[Path]:
        """Every file open this session, working file first.

        This order is the menu's order and it never changes while the session
        is open, so the rows do not move under the cursor between openings.
        """
        if self._path is None:
            return []
        return [self._path, *(self._context_files or [])]

    def _refresh_working_file_chip(self) -> None:
        """Repaint the chip, or do nothing if there is no chip to repaint yet.

        Called from ``on_mount``, where the header's children may not be
        mounted — so *painting* is guarded as well as finding: rendering asks
        the chip for its screen, and an unmounted widget raises rather than
        answering. Letting that escape aborts app startup, which is how a
        header detail became a mount-time crash under load.
        """
        try:
            chip = self.query_one("#working-file", WorkingFileChip)
            chip.update_files(self._path, len(self._context_files or []))
        except Exception:  # noqa: BLE001 — the chip is decoration; never fail startup for it
            return

    # ── opening the menu ──────────────────────────────────────────────────────

    def action_working_file(self) -> None:
        """Open the drop-down (the ``f`` binding, and the chip's own click)."""
        if self._path is None:
            self.notify(_READ_ONLY_MESSAGE, severity=_LIT_WARNING)
            return
        files = self.loaded_files()
        if len(files) < 2:
            self.notify(
                "Only one file is open. Reopen with context files to switch between them.",
                title=_LIT_WORKING_FILE,
            )
            return
        menu = self.query_one("#working-file-menu", WorkingFileMenu)
        menu.show(self._path, files, self._chip_anchor())

    def _chip_anchor(self) -> tuple[int, int]:
        """Where the menu hangs from — the chip's own corner, so it reads as
        belonging to the control that opened it."""
        try:
            chip = self.query_one("#working-file", WorkingFileChip)
            region = chip.region
            return region.x, region.y
        except Exception:  # noqa: BLE001 — keyboard use before a first paint
            return 0, 0

    def on_working_file_chip_pressed(self, event: WorkingFileChip.Pressed) -> None:
        event.stop()
        self.action_working_file()

    def on_working_file_menu_chosen(self, event: WorkingFileMenu.Chosen) -> None:
        event.stop()
        self.switch_working_file(event.path)

    # ── performing the switch ─────────────────────────────────────────────────

    def switch_working_file(self, chosen: Path) -> None:
        """Make *chosen* writable, re-reading it off the UI thread.

        The parse is the expensive half, and it is the same parse that opening
        the file cost in the first place — on a large ontology, seconds. Running
        it inline would freeze the editor mid-switch, which is precisely why
        ``_reload_from_disk`` cannot be reused here: that one is deliberately
        synchronous *because* its browser is still empty.

        Only the work goes to the thread. The decision, and the no-op when the
        chosen file is already the working one, stay here so that picking the
        row you are already on costs nothing at all.
        """
        if self._path is None or chosen == self._path:
            return
        self.run_worker(
            partial(self._switch_worker, chosen),
            thread=True,
            exclusive=True,
            group="working-file-switch",
            name="ster-working-file-switch",
        )

    def _switch_worker(self, chosen: Path) -> None:
        """Run the switch off the UI thread, marshalling every effect back onto it."""
        assert self._path is not None
        try:
            switch(
                chosen,
                current=self._path,
                loaded=self.loaded_files(),
                flush=self._flush_save,
                load=self._load_for_switch,
                apply=self._apply_from_worker,
            )
        except WorkingFileError as exc:
            self.call_from_thread(self._notify_switch, str(exc), failed=True)
            return
        except Exception as exc:  # noqa: BLE001 — a parse error must not kill the editor
            self.call_from_thread(
                self._notify_switch, f"Could not read {chosen.name}: {exc}", failed=True
            )
            return
        self.call_from_thread(self._notify_switch, f"Working file is now {chosen.name}.")

    def _notify_switch(self, message: str, *, failed: bool = False) -> None:
        severity = _LIT_WARNING if failed else "information"
        self.notify(message, title=_LIT_WORKING_FILE, severity=severity)  # type: ignore[arg-type]

    def _apply_from_worker(self, taxonomy, editable: Path, context: list[Path]) -> None:
        """``apply`` as seen from the worker: every widget touch on the UI thread."""
        self.call_from_thread(self._apply_working_file, taxonomy, editable, context)

    def _load_for_switch(self, editable: Path, context: list[Path]):
        from ster import store  # noqa: PLC0415

        self.call_from_thread(self._begin_activity, "switch", f"Opening {editable.name}")
        try:
            return store.load(editable, context=context)
        finally:
            self.call_from_thread(self._end_activity, "switch")

    def _apply_working_file(self, taxonomy, editable: Path, context: list[Path]) -> None:
        """Install the reloaded session and repaint everything the roles changed."""
        self._install_working_file(taxonomy, editable, context)
        self._service = self._make_service(taxonomy, editable)
        self._refresh_search_rows()
        self._invalidate_lint()
        self._rebuild_tree()  # the lock glyphs move with the roles
        self._refresh_working_file_chip()
        self._show(self._detail_uri)
        self._publish_working_file()

    def _publish_working_file(self) -> None:
        """Tell the API server serving this session about the new roles.

        Best-effort, exactly like starting it was: a taken port means no server
        this session, and switching files must work regardless.
        """
        try:
            from ster.api_server import publish_working_file  # noqa: PLC0415

            publish_working_file(self.tax, self._path, self._context_files or [])
        except Exception:  # noqa: BLE001 — publishing context must never break the editor
            pass
