"""A checkbox with a clear, well-sized mark.

Textual's ``ToggleButton`` always draws ``BUTTON_INNER`` (``"X"``) and only *dims* it
for the off state, so an unchecked box reads like a faint mark — you can't tell whether
it is ticked. :class:`Check` renders a bracketed mark instead: ``[ ]`` when off and
``[✓]`` when on (three cells wide, the size Textual lays out for the button), coloured
by the shared ``toggle--button`` style (muted off / bold success on, set in the app
CSS). Being a ``Checkbox`` subclass, it works everywhere a ``Checkbox`` does —
``query(Checkbox)`` / ``isinstance(x, Checkbox)`` still match it.
"""

from __future__ import annotations

from textual.content import Content
from textual.widgets import Checkbox


class Check(Checkbox):
    """A ``Checkbox`` that shows ``[ ]`` (unchecked) / ``[✓]`` (checked)."""

    @property
    def _button(self) -> Content:
        style = self.get_visual_style("toggle--button")
        inner = "✓" if self.value else " "
        return Content.assemble(("[", style), (inner, style), ("]", style))
