"""The busy-spinner status line, background debounced saving, and running a TaxonomyService command through the busy/save machinery."""

from __future__ import annotations

from textual.widgets import Static

from ._constants import _READ_ONLY_MESSAGE
from ._state import _AppState


class _BusySaveMixin(_AppState):
    """Mixin: the busy-spinner status line, background debounced saving, and running a TaxonomyService command through the busy/save machinery."""

    # ── busy indicator (Saving… / Checking…) ──────────────────────────────────
    _SPINNER = "⣾⣽⣻⢿⡿⣟⣯⣷"

    def _begin_activity(self, name: str, label: str) -> None:
        """Show a spinner + *label* (e.g. 'Saving') for a running background job *name*."""
        self._activities[name] = label
        self._refresh_busy()

    def _end_activity(self, name: str) -> None:
        """Clear a finished background job; hides the overlay when none remain."""
        if self._activities.pop(name, None) is not None:
            self._refresh_busy()

    def _refresh_busy(self) -> None:
        """Match the busy overlay + spinner timer to the set of running jobs."""
        try:
            widget = self.query_one("#busy", Static)
        except Exception:  # noqa: BLE001 — a job scheduled before the UI mounts
            return
        if not self._activities:
            widget.display = False
            widget.update("")
            if self._busy_timer is not None:
                self._busy_timer.stop()
                self._busy_timer = None
            return
        widget.display = True
        self._render_busy()
        if self._busy_timer is None:  # animate while off-thread work runs (UI thread is free)
            self._busy_timer = self.set_interval(0.1, self._render_busy)

    def _render_busy(self) -> None:
        """Paint the current spinner frame + every running job's label."""
        self._spinner_frame = (self._spinner_frame + 1) % len(self._SPINNER)
        labels = " · ".join(f"{lbl}…" for lbl in self._activities.values())
        self.query_one("#busy", Static).update(f"{self._SPINNER[self._spinner_frame]} {labels}")

    def _apply_command(
        self, command: object, select: str | None = None, *, focus_tree: bool = False
    ) -> None:
        """Execute *command* via TaxonomyService, then refresh tax + tree + detail.

        The tree highlight lands on the *resulting* entity: a freshly created one when
        *select* names it (reveal the mutation), otherwise the current entity — restored
        after the rebuild so it never jumps to the top. Focus stays in the detail pane;
        the tree cursor moves without stealing keyboard focus (unlike ``jump_to``).

        ``focus_tree`` instead lands keyboard focus on the entity's *tree* node — used when
        the edited row is being deleted, so the user is one Tab/arrow from the detail pane
        rather than stranded on a row that no longer exists.
        """
        if self._service is None or self._path is None:
            self.notify(_READ_ONLY_MESSAGE, severity="warning")
            return
        result = self._service.execute(command, persist=False)  # type: ignore[arg-type]
        if not result.ok:
            self.notify(result.error or "Command failed.", severity="error")
            return
        # The service swapped a fresh authority taxonomy into the workspace.
        self.tax = self._workspace.taxonomies[self._path]
        self._refresh_search_rows()
        self._invalidate_lint()  # the edit may fix/introduce issues
        self._invalidate_source()  # and it certainly changed the Turtle
        self._rebuild_affected(result.affected_uris, select)  # rebuild only the touched pane(s)
        # A freshly created entity (select) is revealed; anything else keeps the
        # highlight on the current entity — following it if the edit renamed its URI.
        target = select if (select is not None and select in self._uri_nodes) else self._detail_uri
        if target is not None and target in self._uri_nodes:
            self._reveal_in_tree(target, focus=focus_tree)  # focus the tree node on delete
        self._show(target)
        if focus_tree:
            self._pending_focus_key = None  # the row is gone; we deliberately left the pane
        else:
            # The mutation rebuilt the detail rows, destroying the row that had focus —
            # restore it (next refresh) so the keyboard keeps working after a modal.
            self.call_after_refresh(self._restore_focus)
        self._schedule_save()  # persist off the UI thread → the window stays responsive
        self._schedule_lint()  # debounce: one lint after a lull, not one per edit

    def _schedule_save(self) -> None:
        """Persist the current authority to disk on a background worker (the slow part of
        an edit). Serialised by ``_save_lock``; a later edit's save supersedes an earlier."""
        if self._service is None or self._path is None:
            return
        self._save_dirty = True
        self._begin_activity("save", "Saving")  # spinner until the worker finishes
        self.run_worker(
            self._save_worker, thread=True, exclusive=True, group="ster-save", name="ster-save"
        )

    def _save_worker(self) -> None:
        from ster import store

        try:
            with self._save_lock:
                tax, path = self.tax, self._path
                if path is not None:
                    store.save(tax, path)
                    # Cleared only once the bytes are on disk, and only if this is
                    # still the authority. A save can be cancelled — run_worker is
                    # exclusive, so a later edit kills this one — or raise; clearing
                    # first left the app believing it was clean, so the quit-time
                    # flush wrote nothing and the edit was lost silently. If an edit
                    # swapped the authority mid-write, that newer one is still
                    # unwritten, so the flag stays up for the next save to catch.
                    if self.tax is tax:
                        self._save_dirty = False
        finally:
            self.call_from_thread(self._end_activity, "save")  # clear the spinner on the UI thread

    def _flush_save(self) -> None:
        """Synchronously persist any unsaved edit — called on quit so a backgrounded save
        can never be lost."""
        from ster import store

        with self._save_lock:
            if self._save_dirty and self._path is not None:
                store.save(self.tax, self._path)
                self._save_dirty = False

    def _install_working_file(self, taxonomy, path, context) -> None:
        """Swap the model, its file and its context together, under the save lock.

        ``_save_worker`` reads ``self.tax`` and ``self._path`` as a pair, so the
        two must never be observable apart: a save that caught a new path beside
        the old model would write one ontology into another ontology's file.
        Changing which file is writable is the only operation that moves both,
        which is why it is the only one that needs this.

        The dirty flag is deliberately not cleared — the caller flushes *before*
        the roles move (see ``ster.working_file.switch``), so anything still
        unsaved here belongs to the model being installed, not the one leaving.
        """
        with self._save_lock:
            self.tax = taxonomy
            self._path = path
            self._context_files = list(context)
