"""The Problems modal: scan-on-open, listing/applying scan-lint fixes, and restoring tree focus afterward."""

from __future__ import annotations

from textual.widgets import Tree

from ._constants import _DETAIL_SELECTOR, _READ_ONLY_MESSAGE, _TREE_SELECTOR
from ._state import _AppState


class _ProblemsMixin(_AppState):
    """Mixin: the Problems modal: scan-on-open, listing/applying scan-lint fixes, and restoring tree focus afterward."""

    def _blocking_errors(self) -> list[dict]:
        """The current ERROR-severity semanticlint issues (empty when the plugin is off
        or the file is clean)."""
        from ster.plugins.semanticlint import fixes

        result = self._ontology_lint()
        return fixes.blocking_errors(result[1]) if result else []

    def _maybe_scan_on_open(self) -> None:
        """First-paint hook: surface blocking errors in the Problems modal, but only when
        the plugin's 'check on open' feature is on. Silent when the file is clean."""
        from ster.plugins.semanticlint import config

        if config.feature_enabled("check_on_open"):
            errors = self._blocking_errors()
            if errors:
                self._open_problems(errors)

    def action_problems(self) -> None:
        """Reopen the Problems worklist, re-scanning first so resolved errors drop off;
        notify when there is nothing left to fix."""
        self._invalidate_lint()
        errors = self._blocking_errors()
        if errors:
            self._open_problems(errors)
        else:
            self.notify("No blocking errors.", severity="information")

    def _open_problems(self, errors: list[dict]) -> None:
        from ster.plugins.semanticlint import fixes
        from ster.tui.plugins.semanticlint_ui.problems_modal import ProblemsModal

        problems = [(issue, fixes.fix_for(issue, self.tax)) for issue in errors]
        self.push_screen(ProblemsModal(problems, self._apply_fix), self._after_problems)

    def _apply_fix(self, issue: dict, choice: str) -> str | None:
        """Apply an inline fix from the Problems modal: build its command(s) and run them
        through the service. None on success (the modal then drops the row); otherwise the
        reason it did not apply, which the modal shows on the row."""
        from ster.plugins.semanticlint import fixes

        if self._path is None:
            return _READ_ONLY_MESSAGE
        commands = fixes.commands_for(issue, self.tax, self._path, choice)
        if not commands:
            return "Nothing to apply for this fix."
        return self._apply_fix_commands(commands)

    def _apply_fix_commands(self, commands: list) -> str | None:
        """Execute fix *commands* via the service — no UI rebuild (the modal is on top;
        the panes refresh when it closes). Returns the first failure's message, else None."""
        if self._service is None or self._path is None:
            return _READ_ONLY_MESSAGE
        for command in commands:
            result = self._service.execute(command, persist=False)  # type: ignore[arg-type]
            if not result.ok:
                return result.error or "Fix failed."
        self.tax = self._workspace.taxonomies[self._path]
        self._refresh_search_rows()
        self._invalidate_lint()
        self._dirty_after_fix = True
        self._schedule_save()
        return None

    def _after_problems(self, _result: object) -> None:
        """The Problems modal closed — if a fix ran, rebuild the panes so the tree/detail
        reflect the edits (deferred while the modal was on top)."""
        if self._dirty_after_fix:
            self._dirty_after_fix = False
            self._rebuild_tree()
            self._show(self._detail_uri)
            self._schedule_lint()

    def _restore_focus(self) -> None:
        """Land focus back on the row that was being edited after a mutation rebuilt the
        panes (so the cursor stays put), falling back to the first row, then the tree.

        A mutation destroys the old row widgets, so we re-find by field key. Value rows
        embed the value in their key (``…::<value>``); when an edit changes the value the
        key changes too, so we also try the stable stem before that separator."""
        rows = [r for r in self.query(f"{_DETAIL_SELECTOR} DetailRow") if r.can_focus]
        if not rows:
            self.query_one(_TREE_SELECTOR, Tree).focus()
            return
        key, self._pending_focus_key = self._pending_focus_key, None
        target = self._row_for_focus_key(rows, key) if key else None
        (target or rows[0]).focus()

    @staticmethod
    def _row_for_focus_key(rows: list, key: str):  # type: ignore[no-untyped-def]
        """The row matching *key* exactly, else one sharing its stable ``…::``-stem."""
        exact = next((r for r in rows if r.field.key == key), None)
        if exact is not None:
            return exact
        stem = key.rsplit("::", 1)[0] + "::" if "::" in key else None
        return next((r for r in rows if stem and r.field.key.startswith(stem)), None)

    def _refocus_edited_row(self) -> None:
        """Focus back the row that was being edited after a *cancel* — value edits open
        from the row's menu (which held focus), so Textual can't restore the row itself."""
        rows = [r for r in self.query(f"{_DETAIL_SELECTOR} DetailRow") if r.can_focus]
        key, self._pending_focus_key = self._pending_focus_key, None
        target = self._row_for_focus_key(rows, key) if (rows and key) else None
        if target is not None:
            target.focus()
