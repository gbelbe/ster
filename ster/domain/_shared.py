"""Cross-layer domain helpers shared by more than one ster.domain module."""

from __future__ import annotations


def _replace_in_list(lst: list[str], old: str, new: str) -> None:
    for i, v in enumerate(lst):
        if v == old:
            lst[i] = new
