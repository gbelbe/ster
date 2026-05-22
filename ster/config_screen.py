"""Standalone curses-based Setup / Options configuration screen."""

from __future__ import annotations

import curses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .nav.ai_model_picker import AiModelPickState
    from .nav.logic import DetailField


def run_config_screen(lang: str = "en") -> None:
    """Launch the full-screen config screen (curses wrapper entry point)."""
    curses.wrapper(_config_main, lang)


def _config_main(stdscr: curses.window, lang: str) -> None:
    from .api_server import load_server_config, save_server_config
    from .nav.logic import build_global_fields

    curses.curs_set(0)
    stdscr.keypad(True)

    server_url, server_port = load_server_config()
    pending_restart = False
    show_token = False
    picker: AiModelPickState | None = None

    def _fields() -> list[DetailField]:
        return build_global_fields(
            None,
            None,
            lang,
            server_url=server_url,
            server_port=server_port,
            show_token=show_token,
            pending_restart=pending_restart,
        )

    fields = _fields()
    sel_idx = [i for i, f in enumerate(fields) if f.meta.get("action") is not None]
    cursor = 0

    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()

        if picker is not None:
            _draw_picker(stdscr, picker, h, w)
            stdscr.refresh()
            key = stdscr.getch()
            if key == curses.KEY_RESIZE:
                curses.update_lines_cols()
                continue
            from .nav.ai_model_picker import on_key

            picker, done = on_key(picker, key)
            if done:
                picker = None
            continue

        fields = _fields()
        sel_idx = [i for i, f in enumerate(fields) if f.meta.get("action") is not None]

        _draw_config(stdscr, fields, sel_idx, cursor, server_url, server_port, h, w)
        stdscr.refresh()

        key = stdscr.getch()

        if key in (27, ord("q"), ord("Q")):
            break

        elif key in (curses.KEY_UP, ord("k")):
            if cursor > 0:
                cursor -= 1

        elif key in (curses.KEY_DOWN, ord("j")):
            if cursor < len(sel_idx) - 1:
                cursor += 1

        elif key in (curses.KEY_ENTER, 10, 13):
            if not sel_idx:
                continue
            field = fields[sel_idx[cursor]]
            action = field.meta.get("action")

            if action == "edit_server_url":
                new_val = _inline_edit(stdscr, h, w, "Server URL", server_url)
                if new_val is not None and new_val.strip():
                    server_url = new_val.strip()
                    save_server_config(server_url, server_port)
                    pending_restart = True

            elif action == "edit_server_port":
                new_val = _inline_edit(stdscr, h, w, "Port", str(server_port))
                if new_val is not None and new_val.strip().isdigit():
                    server_port = int(new_val.strip())
                    save_server_config(server_url, server_port)
                    pending_restart = True

            elif action == "show_bearer_token":
                show_token = not show_token

            elif action == "open_ai_config":
                try:
                    from .nav.ai_model_picker import AiModelPickState, build_top_items

                    picker = AiModelPickState(items=build_top_items(), level="top")
                except Exception:  # noqa: BLE001
                    _show_message(stdscr, h, w, "Could not open AI config")

            elif action == "pick_lang":
                new_lang = _pick_language(stdscr, h, w, lang)
                if new_lang:
                    lang = new_lang
                    _save_lang(lang)


def _draw_picker(
    stdscr: curses.window,
    st: AiModelPickState,
    h: int,
    w: int,
) -> None:
    try:
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        use_color = True
    except Exception:
        use_color = False

    # Title (level-aware)
    _LEVEL_TITLE = {
        "top": " ster — Configure AI Model ",
        "local": " ster — Local Model ",
        "external": " ster — External Model ",
        "endpoint": " ster — Custom Endpoint ",
    }
    title = _LEVEL_TITLE.get(st.level, " ster — Configure AI Model ")
    try:
        stdscr.attron(curses.A_BOLD)
        stdscr.addstr(0, 0, title.center(w)[:w])
        stdscr.attroff(curses.A_BOLD)
    except curses.error:
        pass

    # Show currently configured backend
    try:
        from . import ai

        ep = ai.get_endpoint_config()
        cp = ai.is_copypaste()
        if cp:
            active_line = "  Active: copy-paste mode"
        elif ep.get("url") and ep.get("model"):
            active_line = f"  Active: {ep['url']}  ({ep['model']})"
        else:
            current = ai.get_saved_model()
            active_line = f"  Active: {current}" if current else "  No model configured yet"
        if use_color:
            stdscr.attron(curses.color_pair(1))
        stdscr.addstr(1, 0, active_line[:w])
        if use_color:
            stdscr.attroff(curses.color_pair(1))
    except Exception:  # noqa: BLE001
        pass

    list_h = h - 6  # rows available for the scrollable list
    row = 3
    for i in range(list_h):
        idx = st.scroll + i
        if idx >= len(st.items):
            break
        mid, label = st.items[idx]
        is_sel = idx == st.cursor
        try:
            if is_sel:
                if use_color:
                    stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
                stdscr.addstr(row, 2, f"▶ {label}"[: w - 2])
                if use_color:
                    stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
            else:
                stdscr.addstr(row, 4, label[: w - 4])
        except curses.error:
            pass
        row += 1

    # Key prompt at bottom
    if st.key_prompt:
        try:
            curses.curs_set(1)
            label = st.key_name if st.ep_field else f"API key ({st.key_name})"
            visible = st.key_buffer if st.ep_field else "*" * len(st.key_buffer)
            prompt_str = f"  {label}: "
            display = prompt_str + visible
            if use_color:
                stdscr.attron(curses.color_pair(2))
            stdscr.addstr(h - 3, 0, display[:w])
            if use_color:
                stdscr.attroff(curses.color_pair(2))
        except curses.error:
            pass
        if st.error:
            try:
                if use_color:
                    stdscr.attron(curses.color_pair(3))
                stdscr.addstr(h - 2, 2, st.error[:w])
                if use_color:
                    stdscr.attroff(curses.color_pair(3))
            except curses.error:
                pass
        hint = "  Enter: save   Esc: back"
    else:
        curses.curs_set(0)
        if st.error:
            try:
                if use_color:
                    stdscr.attron(curses.color_pair(3))
                stdscr.addstr(h - 2, 2, st.error[:w])
                if use_color:
                    stdscr.attroff(curses.color_pair(3))
            except curses.error:
                pass
        if st.level == "top":
            hint = "  ↑↓  navigate   Enter: select   Esc: close"
        elif st.level == "endpoint":
            hint = "  ↑↓  navigate   Enter: edit field / save   Esc: back"
        else:
            hint = "  ↑↓  navigate   Enter: select   Esc: back"

    try:
        if use_color:
            stdscr.attron(curses.A_DIM)
        stdscr.addstr(h - 1, 0, hint[:w])
        if use_color:
            stdscr.attroff(curses.A_DIM)
    except curses.error:
        pass


def _draw_config(
    stdscr: curses.window,
    fields: list[DetailField],
    sel_idx: list[int],
    cursor: int,
    server_url: str,
    server_port: int,
    h: int,
    w: int,
) -> None:
    try:
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_GREEN, -1)
        use_color = True
    except Exception:
        use_color = False

    selected_field_idx = sel_idx[cursor] if sel_idx and cursor < len(sel_idx) else -1

    title = " ster — Setup / Options "
    try:
        stdscr.attron(curses.A_BOLD)
        stdscr.addstr(0, 0, title.center(w)[:w])
        stdscr.attroff(curses.A_BOLD)
    except curses.error:
        pass

    full_addr = f"  Server address: {server_url}:{server_port}"
    try:
        if use_color:
            stdscr.attron(curses.color_pair(4))
        stdscr.addstr(1, 0, full_addr[:w])
        if use_color:
            stdscr.attroff(curses.color_pair(4))
    except curses.error:
        pass

    row = 3
    for i, f in enumerate(fields):
        if row >= h - 2:
            break
        ftype = f.meta.get("type")

        if ftype == "separator":
            label = f"── {f.display} "
            label = label + "─" * max(0, w - len(label) - 2)
            try:
                if use_color:
                    stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
                stdscr.addstr(row, 0, label[:w])
                if use_color:
                    stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
            except curses.error:
                pass
            row += 1
            continue

        if ftype == "warning":
            warn = f"  ⚠  {f.value}"
            try:
                if use_color:
                    stdscr.attron(curses.color_pair(3) | curses.A_BOLD)
                stdscr.addstr(row, 0, warn[:w])
                if use_color:
                    stdscr.attroff(curses.color_pair(3) | curses.A_BOLD)
            except curses.error:
                pass
            row += 1
            continue

        is_selected = i == selected_field_idx
        label_col = 4
        value_col = 26
        label_str = f.display
        value_str = f.value or ""

        try:
            if is_selected:
                prefix = "▶ "
                if use_color:
                    stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
                line = f"{prefix}{label_str:<{value_col - label_col - 2}}  {value_str}"
                stdscr.addstr(row, label_col - 2, line[: w - label_col + 2])
                if use_color:
                    stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
            else:
                stdscr.addstr(
                    row, label_col, f"{label_str:<{value_col - label_col}}"[: w - label_col]
                )
                stdscr.addstr(row, value_col, value_str[: w - value_col])
        except curses.error:
            pass

        row += 1

    hint = "  ↑↓  navigate   Enter: edit / toggle   Esc: back"
    try:
        if use_color:
            stdscr.attron(curses.A_DIM)
        stdscr.addstr(h - 1, 0, hint[:w])
        if use_color:
            stdscr.attroff(curses.A_DIM)
    except curses.error:
        pass


def _inline_edit(
    stdscr: curses.window,
    h: int,
    w: int,
    label: str,
    current: str,
) -> str | None:
    """Show an inline edit prompt at the bottom of the screen; return new value or None."""
    curses.curs_set(1)
    prompt = f"  {label}: "
    buf = list(current)
    pos = len(buf)

    while True:
        try:
            stdscr.move(h - 2, 0)
            stdscr.clrtoeol()
            stdscr.addstr(h - 2, 0, (prompt + "".join(buf))[:w])
            stdscr.move(h - 2, min(len(prompt) + pos, w - 1))
        except curses.error:
            pass
        stdscr.refresh()

        key = stdscr.getch()
        if key in (10, 13):
            curses.curs_set(0)
            return "".join(buf)
        elif key == 27:
            curses.curs_set(0)
            return None
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if pos > 0:
                buf.pop(pos - 1)
                pos -= 1
        elif key == curses.KEY_LEFT:
            pos = max(0, pos - 1)
        elif key == curses.KEY_RIGHT:
            pos = min(len(buf), pos + 1)
        elif 32 <= key <= 126:
            buf.insert(pos, chr(key))
            pos += 1


def _show_message(stdscr: curses.window, h: int, w: int, msg: str) -> None:
    """Flash a one-line message at the bottom for a single key press."""
    try:
        stdscr.addstr(h - 2, 2, msg[: w - 4])
        stdscr.refresh()
        stdscr.getch()
    except curses.error:
        pass


def _pick_language(
    stdscr: curses.window,
    h: int,
    w: int,
    current: str,
) -> str | None:
    return _inline_edit(stdscr, h, w, "Language code (e.g. en, fr)", current)


def _save_lang(lang: str) -> None:
    try:
        from pathlib import Path

        from .project import Project

        p = Project.load(Path.cwd())
        if p is not None:
            p.lang = lang
            p.save()
    except Exception:  # noqa: BLE001
        pass
