"""Semanticlint integration: computing/caching lint results in the background, debounced re-lint after edits, and the lint report modal."""

from __future__ import annotations

from ..detail_view import DetailRow
from ._state import _AppState


class _LintMixin(_AppState):
    """Mixin: semanticlint integration: computing/caching lint results in the background, debounced re-lint after edits, and the lint report modal."""

    def _ontology_lint(self) -> tuple[dict, list] | None:
        """semanticlint result for the file (computed once per session, cached).

        ``None`` when the semanticlint plugin is disabled / not installed, so no lint
        colours, rows or modal appear — ster behaves as standard."""
        from ster.plugins import semanticlint

        if self._path is None or not semanticlint.is_active():
            return None
        if not self._lint_computed:
            self._set_lint(self._compute_lint())
        return self._lint_cache

    def _compute_lint(self) -> tuple[dict, list] | None:
        """Return the semanticlint result, from the md5+config disk cache when the file is
        unchanged, else compute (blocking, ~2 s on a large ontology) and cache it. ``None``
        on any failure — a lint error must never break the view."""
        path = self._path
        if path is None:
            return None
        try:
            # Imported inside the try: a present-but-broken semanticlint (import raises)
            # must degrade to "no lint", never crash the view — the import itself can
            # fail, not just the computation.
            from ster.plugins.semanticlint import config, lint_cache
            from ster.plugins.semanticlint.runner import lint_overview

            cfg_hash = lint_cache.config_hash(config.load_config())
            return lint_cache.get_or_compute(path, cfg_hash, compute=lambda: lint_overview(path))
        except Exception:  # noqa: BLE001
            return None

    def _set_lint(self, result: tuple[dict, list] | None) -> None:
        """Store a fresh lint result + rebuild the uri→worst-severity index and the
        uri→issues index (the latter drives the hover tooltip, O(1) per hover)."""
        from ster.plugins.semanticlint import report

        self._lint_cache = result
        self._lint_computed = True
        self._lint_index = report.worst_by_subject(result[1]) if result else {}
        self._lint_issues = report.issues_by_subject(result[1]) if result else {}

    #: seconds of edit inactivity before the (heavy) re-lint fires — comfortably longer
    #: than a large-file background save, so the file-based lint reads the fresh state.
    _LINT_DEBOUNCE = 1.5

    def _schedule_lint(self) -> None:
        """Debounce the heavy re-lint: recompute only after a lull, so a burst of edits
        triggers one lint pass instead of one per edit (each ~2 s on a large ontology)."""
        if self._lint_timer is not None:
            self._lint_timer.stop()
        self._lint_timer = self.set_timer(self._LINT_DEBOUNCE, self._refresh_lint_async)

    def _refresh_lint_async(self) -> None:
        """Recompute lint off the UI thread (when the plugin is active), then recolour
        the tree and refresh the open detail. No-op otherwise."""
        from ster.plugins import semanticlint

        if self._path is None or not semanticlint.is_active():
            self._set_lint(None)
            return
        self._begin_activity("lint", "Checking")  # spinner while the background check runs
        self.run_worker(
            self._lint_worker, thread=True, exclusive=True, group="lint", name="ster-lint"
        )

    def _lint_worker(self) -> None:
        result = self._compute_lint()
        self.call_from_thread(self._on_lint_ready, result)

    def _on_lint_ready(self, result: tuple[dict, list] | None) -> None:
        """Apply a background lint result on the UI thread: recolour + refresh.

        The debounced lint lands a second or two *after* an edit, when focus is back on a
        detail row. ``_show`` rebuilds (and so destroys) that row, which would drop focus to
        the tree — so we remember the focused row and restore it after the rebuild."""
        self._end_activity("lint")  # the background check finished → clear its spinner
        self._set_lint(result)
        focused = self.focused
        keep_key = focused.field.key if isinstance(focused, DetailRow) else None
        self._rebuild_tree()
        if self._detail_uri:
            # Re-reveal the current entity so the recolour rebuild doesn't collapse
            # ancestors / reset the cursor (without stealing focus from a detail row).
            self._reveal_in_tree(self._detail_uri, focus=False)
            self._show(self._detail_uri)
            if keep_key is not None:  # keep the cursor on the row the user was on
                self._pending_focus_key = keep_key
                self.call_after_refresh(self._restore_focus)

    def _invalidate_lint(self) -> None:
        """Drop the cached lint so the next access (or the async worker) recomputes."""
        self._lint_cache = None
        self._lint_computed = False
        self._lint_index = {}
        self._lint_issues = {}

    def _open_lint(self, severity: str | None = None) -> None:
        """Open a modal listing the semanticlint issues of *severity* (a read-only
        view). Selecting an issue that points at a known entity jumps straight to
        it (e.g. a missing-label warning → that class), so it can be fixed in place.
        """
        from ..lint_modal import LintModal

        result = self._ontology_lint()
        issues = result[1] if result else []
        if severity:
            issues = [i for i in issues if i.get("severity") == severity]
        kind = {"error": "Errors", "warning": "Warnings"}.get(severity or "", "semanticlint")
        self.push_screen(
            LintModal(issues, set(self._uri_nodes), kind=kind), self._goto_lint_subject
        )

    def _goto_lint_subject(self, subject: str | None) -> None:
        """Callback for the lint modal: navigate to the chosen issue's subject."""
        if subject:
            self.jump_to(subject)
