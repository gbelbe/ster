"""Standalone curses-based AI model configuration wizard."""

from __future__ import annotations

import curses
import sys

from .nav.draw import _C_NAVIGABLE, _C_SEL
from .nav.state import AiInstallState, AiSetupState


class AiConfigWizard:
    """Full-screen AI model configuration wizard (extracted from TaxonomyViewer)."""

    _SPINNER = "|/-\\"

    def __init__(self) -> None:
        from . import ai

        if not ai.is_available():
            self._state: AiSetupState | AiInstallState = AiInstallState()
        else:
            online, offline = ai.discover_models()
            cp_idx = (1 if online else 0) + (1 if offline else 0)
            self._state = AiSetupState(
                online_providers=online,
                offline_providers=offline,
                provider_cursor=cp_idx if ai.is_copypaste() else 0,
            )

        self._install_thread: object = None
        self._install_output: list[str] = []
        self._install_returncode: int | None = None
        self._install_spinner: int = 0
        self._install_package: str = "llm"
        self._install_command: list[str] | None = None

    def run(self, stdscr: curses.window) -> None:
        curses.curs_set(0)
        stdscr.keypad(True)

        while True:
            rows, cols = stdscr.getmaxyx()
            stdscr.erase()
            self.draw(stdscr, rows, cols)
            stdscr.refresh()

            if isinstance(self._state, AiInstallState) and self._state.installing:
                self.install_poll()
                curses.napms(120)
                continue

            if isinstance(self._state, AiSetupState) and self._state.plugin_installing:
                self.plugin_poll()
                curses.napms(120)
                continue

            key = stdscr.getch()
            if key == curses.KEY_RESIZE:
                curses.update_lines_cols()
                continue
            if key == -1:
                continue
            if self.on_key(key):
                break

    def on_key(self, key: int) -> bool:
        """Process a key; return True when the wizard should close."""
        if isinstance(self._state, AiInstallState):
            return self._on_install_key(key)
        if isinstance(self._state, AiSetupState):
            return self._on_setup_key(key)
        return True

    # ── Install step ──────────────────────────────────────────────────────────

    def _on_install_key(self, key: int) -> bool:
        st = self._state
        assert isinstance(st, AiInstallState)
        if st.done:
            from . import ai

            online, offline = ai.discover_models()
            self._state = AiSetupState(
                online_providers=online,
                offline_providers=offline,
            )
            return False
        if st.error:
            if key == 27:
                return True
        elif key == 27:
            return True
        elif key in (ord("\n"), ord("\r"), 343):
            self._install_thread = None
            self._install_output = []
            self._install_returncode = None
            self._install_spinner = 0
            self._state = AiInstallState(
                pending_action=st.pending_action,
                installing=True,
            )
        return False

    # ── Setup wizard steps ────────────────────────────────────────────────────

    def _on_setup_key(self, key: int) -> bool:  # noqa: C901
        from . import ai as _ai

        st = self._state
        assert isinstance(st, AiSetupState)

        KEY_UP, KEY_DOWN = 259, 258

        def _s(**kw: object) -> AiSetupState:
            import dataclasses

            return dataclasses.replace(st, **kw)  # type: ignore[arg-type]

        providers = st.online_providers if st.mode == "online" else st.offline_providers

        if st.step == "mode":
            avail = []
            if st.online_providers:
                avail.append("online")
            if st.offline_providers:
                avail.append("offline")
            avail.append("copypaste")
            n = len(avail)
            if key == 27:
                return True
            elif n > 0 and key in (KEY_UP, ord("k")):
                self._state = _s(provider_cursor=(st.provider_cursor - 1) % n)
            elif n > 0 and key in (KEY_DOWN, ord("j")):
                self._state = _s(provider_cursor=(st.provider_cursor + 1) % n)
            elif n > 0 and key in (ord("\n"), ord("\r"), 343):
                mode = avail[st.provider_cursor]
                if mode == "copypaste":
                    _ai.save_copypaste(True)
                    self._state = _s(step="done", mode="copypaste")
                else:
                    _ai.save_copypaste(False)
                    self._state = _s(
                        step="provider", mode=mode, provider_cursor=0, provider_scroll=0
                    )

        elif st.step == "provider":
            n = len(providers) + 1
            install_idx = len(providers)
            if key == 27:
                self._state = _s(step="mode", provider_cursor=0)
            elif key in (KEY_UP, ord("k")):
                c = max(0, st.provider_cursor - 1)
                self._state = _s(provider_cursor=c, provider_scroll=min(st.provider_scroll, c))
            elif key in (KEY_DOWN, ord("j")):
                c = min(n - 1, st.provider_cursor + 1)
                self._state = _s(provider_cursor=c, provider_scroll=max(st.provider_scroll, c - 3))
            elif key in (ord("\n"), ord("\r"), 343):
                if st.provider_cursor == install_idx:
                    from . import ai as _ai_mod

                    installed = {p[0] for p in st.online_providers + st.offline_providers}
                    plugins = _ai_mod.available_plugins(installed)
                    self._state = _s(
                        step="install_plugin",
                        available_plugins=plugins,
                        plugin_cursor=0,
                        plugin_scroll=0,
                        plugin_installing=False,
                        plugin_done=False,
                        plugin_error="",
                        plugin_lines=[],
                        selected_plugin_pkg="",
                        selected_plugin_label="",
                    )
                else:
                    pid, _, _ = providers[st.provider_cursor]
                    self._state = _s(
                        step="model",
                        selected_provider_id=pid,
                        model_cursor=0,
                        model_scroll=0,
                        error="",
                    )

        elif st.step == "install_plugin":
            if st.plugin_done:
                if key in (27, ord("\n"), ord("\r"), 343):
                    from . import ai as _ai_mod

                    online, offline = _ai_mod.discover_models()
                    self._state = _s(
                        step="provider",
                        online_providers=online,
                        offline_providers=offline,
                        provider_cursor=0,
                        provider_scroll=0,
                        plugin_installing=False,
                        plugin_done=False,
                        plugin_error="",
                        plugin_lines=[],
                        selected_plugin_pkg="",
                        selected_plugin_label="",
                    )
            elif st.plugin_error:
                if key == 27:
                    self._state = _s(
                        plugin_error="", selected_plugin_pkg="", selected_plugin_label=""
                    )
            elif not st.plugin_installing:
                plugins = st.available_plugins
                n = len(plugins)
                if key == 27:
                    self._state = _s(step="provider", provider_cursor=0, provider_scroll=0)
                elif n > 0 and key in (KEY_UP, ord("k")):
                    c = max(0, st.plugin_cursor - 1)
                    self._state = _s(plugin_cursor=c, plugin_scroll=min(st.plugin_scroll, c))
                elif n > 0 and key in (KEY_DOWN, ord("j")):
                    c = min(n - 1, st.plugin_cursor + 1)
                    self._state = _s(plugin_cursor=c, plugin_scroll=max(st.plugin_scroll, c - 3))
                elif n > 0 and key in (ord("\n"), ord("\r"), 343):
                    _, lbl, pkg = plugins[st.plugin_cursor]
                    self._install_package = pkg
                    self._install_output = []
                    self._install_returncode = None
                    self._install_spinner = 0
                    self._install_thread = None
                    self._state = _s(
                        plugin_installing=True,
                        selected_plugin_pkg=pkg,
                        selected_plugin_label=lbl,
                        plugin_lines=[],
                    )

        elif st.step == "model":
            provider = next((p for p in providers if p[0] == st.selected_provider_id), None)
            models = provider[2] if provider else []
            n = len(models)
            if key in (ord("r"), ord("R")):
                online, offline = _ai.discover_models()
                self._state = _s(
                    online_providers=online,
                    offline_providers=offline,
                    model_cursor=0,
                    model_scroll=0,
                    error="",
                )
            elif key == 27:
                self._state = _s(step="provider", error="")
            elif n == 0 and key in (KEY_UP, ord("k")):
                self._state = _s(model_cursor=max(0, st.model_cursor - 1))
            elif n == 0 and key in (KEY_DOWN, ord("j")):
                is_ollama = st.selected_provider_id == "llm_ollama"
                n_actions = 3 if is_ollama else 2
                self._state = _s(model_cursor=min(n_actions - 1, st.model_cursor + 1))
            elif n == 0 and key in (ord("\n"), ord("\r"), 343):
                is_ollama = st.selected_provider_id == "llm_ollama"
                if st.model_cursor == 0:
                    online, offline = _ai.discover_models()
                    self._state = _s(
                        online_providers=online,
                        offline_providers=offline,
                        model_cursor=0,
                        model_scroll=0,
                        error="",
                    )
                elif is_ollama and st.model_cursor == 1:
                    self._state = _s(
                        step="ollama_pull",
                        buffer="llama3",
                        pos=len("llama3"),
                        plugin_installing=False,
                        plugin_done=False,
                        plugin_error="",
                        plugin_lines=[],
                        selected_plugin_label="",
                    )
                else:
                    self._state = _s(step="model_input", buffer="", pos=0, error="")
            elif n > 0 and key in (KEY_UP, ord("k")):
                c = max(0, st.model_cursor - 1)
                self._state = _s(model_cursor=c, model_scroll=min(st.model_scroll, c))
            elif n > 0 and key in (KEY_DOWN, ord("j")):
                c = min(n - 1, st.model_cursor + 1)
                self._state = _s(model_cursor=c, model_scroll=max(st.model_scroll, c - 3))
            elif n > 0 and key in (ord("\n"), ord("\r"), 343):
                mid = models[st.model_cursor][0]
                key_name = _ai.model_needs_key(mid)
                if key_name:
                    self._state = _s(
                        step="key",
                        selected_model_id=mid,
                        key_name=key_name,
                        buffer="",
                        pos=0,
                        error="",
                    )
                else:
                    _ai.save_model(mid)
                    self._state = _s(step="done", selected_model_id=mid)

        elif st.step == "ollama_pull":
            if st.plugin_done:
                if key in (27, ord("\n"), ord("\r"), 343):
                    online, offline = _ai.discover_models()
                    self._state = _s(
                        step="model",
                        online_providers=online,
                        offline_providers=offline,
                        model_cursor=0,
                        model_scroll=0,
                        plugin_installing=False,
                        plugin_done=False,
                        plugin_error="",
                        plugin_lines=[],
                        error="",
                    )
            elif st.plugin_error:
                if key == 27:
                    self._state = _s(
                        plugin_error="",
                        plugin_installing=False,
                        plugin_done=False,
                        plugin_lines=[],
                        buffer="llama3",
                        pos=len("llama3"),
                    )
            elif st.plugin_installing:
                pass
            else:
                if key == 27:
                    self._state = _s(step="model", model_cursor=1, error="")
                elif key in (ord("\n"), ord("\r"), 343):
                    import shutil

                    model_name = st.buffer.strip()
                    if not model_name:
                        self._state = _s(plugin_error="Please enter a model name.")
                    else:
                        ollama_path = shutil.which("ollama")
                        if not ollama_path:
                            self._state = _s(
                                plugin_error=(
                                    "'ollama' not found. Install from https://ollama.com/download"
                                )
                            )
                        else:
                            self._install_command = [ollama_path, "pull", model_name]
                            self._install_output = []
                            self._install_returncode = None
                            self._install_spinner = 0
                            self._install_thread = None
                            self._state = _s(
                                plugin_installing=True,
                                selected_plugin_label=model_name,
                                plugin_lines=[],
                                plugin_error="",
                            )
                else:
                    buf, pos = st.buffer, st.pos
                    KEY_BS = curses.KEY_BACKSPACE
                    if key in (KEY_BS, 127, 8):
                        buf, pos = buf[: pos - 1] + buf[pos:], max(0, pos - 1)
                    elif key == curses.KEY_LEFT:
                        pos = max(0, pos - 1)
                    elif key == curses.KEY_RIGHT:
                        pos = min(len(buf), pos + 1)
                    elif key == 1:
                        pos = 0
                    elif key == 5:
                        pos = len(buf)
                    elif key == 11:
                        buf, pos = buf[:pos], pos
                    elif 32 <= key < 256:
                        buf = buf[:pos] + chr(key) + buf[pos:]
                        pos += 1
                    self._state = _s(buffer=buf, pos=pos, plugin_error="")

        elif st.step == "model_input":
            if key == 27:
                self._state = _s(step="model", model_cursor=2, error="")
            elif key in (ord("\n"), ord("\r"), 343):
                mid = st.buffer.strip()
                if not mid:
                    self._state = _s(error="Please enter a model ID.")
                else:
                    key_name = _ai.model_needs_key(mid)
                    if key_name:
                        self._state = _s(
                            step="key",
                            selected_model_id=mid,
                            key_name=key_name,
                            buffer="",
                            pos=0,
                            error="",
                        )
                    else:
                        _ai.save_model(mid)
                        self._state = _s(step="done", selected_model_id=mid)
            else:
                buf, pos = st.buffer, st.pos
                KEY_BS = curses.KEY_BACKSPACE
                if key in (KEY_BS, 127, 8):
                    buf, pos = buf[: pos - 1] + buf[pos:], max(0, pos - 1)
                elif key == curses.KEY_LEFT:
                    pos = max(0, pos - 1)
                elif key == curses.KEY_RIGHT:
                    pos = min(len(buf), pos + 1)
                elif key == 1:
                    pos = 0
                elif key == 5:
                    pos = len(buf)
                elif key == 11:
                    buf, pos = buf[:pos], pos
                elif 32 <= key < 256:
                    buf = buf[:pos] + chr(key) + buf[pos:]
                    pos += 1
                self._state = _s(buffer=buf, pos=pos, error="")

        elif st.step == "key":
            if key == 27:
                from . import ai as _ai2

                _ai2.save_model(st.selected_model_id)
                self._state = _s(step="done", error="")
            elif key in (ord("\n"), ord("\r"), 343):
                if st.buffer.strip():
                    from . import ai as _ai2

                    _ai2.save_key(st.key_name, st.buffer.strip())
                    _ai2.save_model(st.selected_model_id)
                    self._state = _s(step="done", error="")
                else:
                    self._state = _s(error="Enter a key value or press Esc to skip")
            elif key in (263, 127, 8):
                self._state = _s(buffer=st.buffer[:-1], pos=max(0, st.pos - 1))
            elif 32 <= key < 256:
                self._state = _s(buffer=st.buffer + chr(key), pos=st.pos + 1)

        elif st.step == "done":
            return True

        return False

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, stdscr: curses.window, rows: int, cols: int) -> None:
        if isinstance(self._state, AiInstallState):
            self._draw_install(stdscr, rows, cols)
        elif isinstance(self._state, AiSetupState):
            self._draw_setup(stdscr, rows, cols)

    def _draw_install(self, stdscr: curses.window, rows: int, cols: int) -> None:
        st = self._state
        assert isinstance(st, AiInstallState)
        box_w = min(72, cols - 4)
        body_lines = 3
        box_h = body_lines + 6
        y0 = max(0, (rows - box_h) // 2)
        x0 = max(0, (cols - box_w) // 2)
        attr = curses.color_pair(_C_SEL)
        for i in range(box_h):
            try:
                stdscr.addstr(y0 + i, x0, " " * box_w, attr)
            except curses.error:
                pass

        def _put(row: int, text: str, bold: bool = False) -> None:
            a = attr | (curses.A_BOLD if bold else 0)
            try:
                stdscr.addstr(y0 + row, x0 + 2, text[: box_w - 4], a)
            except curses.error:
                pass

        def _center(row: int, text: str, bold: bool = False) -> None:
            a = attr | (curses.A_BOLD if bold else 0)
            pad = max(0, (box_w - len(text)) // 2)
            try:
                stdscr.addstr(y0 + row, x0 + pad, text[:box_w], a)
            except curses.error:
                pass

        if st.done:
            _center(0, " ✓  AI dependency installed ", bold=True)
            _center(2, "llm is ready to use.")
            _center(box_h - 2, "[Enter] continue to model setup    [Esc] cancel")
        elif st.error:
            _center(0, " Installation failed ", bold=True)
            _put(2, st.error)
            _center(box_h - 2, "[Esc] close")
        elif st.installing:
            spinner = self._SPINNER[self._install_spinner % 4]
            _center(0, f" {spinner}  Installing llm… ", bold=True)
            recent = st.lines[-(body_lines):]
            for i, line in enumerate(recent):
                _put(2 + i, line)
            bar_w = box_w - 6
            pos = (len(st.lines) * 4) % (bar_w * 2)
            filled = min(pos, bar_w - pos) if pos > bar_w else pos
            filled = max(2, filled)
            bar = "█" * filled + "░" * (bar_w - filled)
            _put(2 + body_lines + 1, f"[{bar}]")
        else:
            _center(0, " Install AI dependency ", bold=True)
            _center(2, "The 'llm' package is required for AI features.")
            _center(4, "It will be installed into the current Python environment.")
            _center(box_h - 2, "[Enter] install now    [Esc] cancel")

    def _draw_setup(self, stdscr: curses.window, rows: int, cols: int) -> None:  # noqa: C901
        st = self._state
        assert isinstance(st, AiSetupState)
        box_w = min(72, cols - 4)
        list_h = max(4, rows - 10)
        box_h = min(rows - 2, list_h + 8)
        y0 = max(0, (rows - box_h) // 2)
        x0 = max(0, (cols - box_w) // 2)
        attr = curses.color_pair(_C_SEL)
        for i in range(box_h):
            try:
                stdscr.addstr(y0 + i, x0, " " * box_w, attr)
            except curses.error:
                pass

        def _put(row: int, text: str, bold: bool = False, hl: bool = False) -> None:
            a = (
                (curses.color_pair(_C_NAVIGABLE) | curses.A_BOLD)
                if hl
                else (attr | (curses.A_BOLD if bold else 0))
            )
            try:
                stdscr.addstr(y0 + row, x0 + 2, text[: box_w - 4], a)
            except curses.error:
                pass

        def _center(row: int, text: str, bold: bool = False) -> None:
            a = attr | (curses.A_BOLD if bold else 0)
            pad = max(0, (box_w - len(text)) // 2)
            try:
                stdscr.addstr(y0 + row, x0 + pad, text[:box_w], a)
            except curses.error:
                pass

        def _draw_list(
            items: list[tuple[str, str]], cursor: int, scroll: int, row_start: int
        ) -> None:
            for i in range(list_h):
                idx = scroll + i
                if idx >= len(items) or row_start + i >= box_h - 2:
                    break
                _, lbl = items[idx]
                _put(row_start + i, ("▶ " if idx == cursor else "  ") + lbl, hl=(idx == cursor))

        providers = st.online_providers if st.mode == "online" else st.offline_providers

        if st.step == "mode":
            _center(0, " Configure AI model ", bold=True)
            _put(2, "How do you want to run the AI?")
            modes = []
            if st.online_providers:
                modes.append("☁  Online  — cloud API (requires an API key)")
            if st.offline_providers:
                modes.append("⬛  Offline — local model (no key, runs on your machine)")
            modes.append("📋  Copy-paste — display prompt, paste response from any web AI")
            if not modes:
                _put(4, "No models found. Install llm plugins first:")
                _put(5, "  pip install llm-anthropic   # Claude")
                _put(6, "  pip install llm-ollama      # Ollama (local)")
                _put(7, "  pip install llm-gemini      # Gemini")
            else:
                for i, lbl in enumerate(modes):
                    _put(
                        4 + i,
                        ("▶ " if i == st.provider_cursor else "  ") + lbl,
                        hl=(i == st.provider_cursor),
                    )
            _center(box_h - 2, "[↑↓] choose    [Enter] select    [Esc] cancel")

        elif st.step == "provider":
            mode_label = (
                "Online providers  (API key required)"
                if st.mode == "online"
                else "Local / offline providers"
            )
            _center(0, f" {mode_label} ", bold=True)
            items = [(p[0], p[1]) for p in providers] + [("__install__", "+ Install more…")]
            _draw_list(items, st.provider_cursor, st.provider_scroll, 2)
            if st.error:
                _put(box_h - 3, st.error)
            _center(box_h - 2, "[↑↓] choose    [Enter] select    [Esc] back")

        elif st.step == "ollama_pull":
            if st.plugin_installing:
                spinner = self._SPINNER[self._install_spinner % 4]
                _center(0, f" {spinner}  Pulling {st.selected_plugin_label}… ", bold=True)
                recent = st.plugin_lines[-(list_h - 4) :]
                for i, line in enumerate(recent):
                    _put(2 + i, line)
            elif st.plugin_done:
                _center(0, f" ✓  {st.selected_plugin_label} pulled ", bold=True)
                _center(box_h - 2, "[Enter / Esc] continue")
            elif st.plugin_error:
                _center(0, " Pull failed ", bold=True)
                _put(2, st.plugin_error[: box_w - 4])
                _put(3, "Check that the Ollama daemon is running.")
                _center(box_h - 2, "[Esc] back")
            else:
                _center(0, " Pull an Ollama model ", bold=True)
                _put(2, "Enter the model name to pull (e.g. llama3, mistral, phi3):")
                buf, pos = st.buffer, st.pos
                bar_w = box_w - 8
                offset = max(0, pos - bar_w + 1)
                visible = buf[offset : offset + bar_w]
                cursor_rel = pos - offset
                display = visible[:cursor_rel] + "▌" + visible[cursor_rel:]
                _put(4, f"Model:  {display[: bar_w + 1]}", bold=True)
                if st.plugin_error:
                    _put(6, st.plugin_error[: box_w - 4])
                _center(box_h - 2, "[Enter] pull    [Esc] back")

        elif st.step == "install_plugin":
            if st.plugin_installing:
                spinner = self._SPINNER[self._install_spinner % 4]
                _center(0, f" {spinner}  Installing {st.selected_plugin_label}… ", bold=True)
                recent = st.plugin_lines[-(list_h - 4) :]
                for i, line in enumerate(recent):
                    _put(2 + i, line)
                bar_w = box_w - 6
                p = (len(st.plugin_lines) * 4) % (bar_w * 2)
                filled = min(p, bar_w - p) if p > bar_w else p
                bar = "█" * max(2, filled) + "░" * (bar_w - max(2, filled))
                _put(min(box_h - 3, 2 + len(recent) + 1), f"[{bar}]")
            elif st.plugin_done:
                _center(0, f" ✓  {st.selected_plugin_label} installed ", bold=True)
                _center(box_h - 2, "[Enter / Esc] back to provider list")
            elif st.plugin_error:
                _center(0, " Installation failed ", bold=True)
                _put(2, st.plugin_error[: box_w - 4])
                _center(box_h - 2, "[Esc] back")
            else:
                _center(0, " Install a provider plugin ", bold=True)
                plugins = st.available_plugins
                if plugins:
                    _draw_list(
                        [(p[0], p[1]) for p in plugins], st.plugin_cursor, st.plugin_scroll, 2
                    )
                else:
                    _put(3, "All known providers are already installed.")
                _center(box_h - 2, "[↑↓] choose    [Enter] install    [Esc] back")

        elif st.step == "model":
            provider = next((p for p in providers if p[0] == st.selected_provider_id), None)
            pname = provider[1].split("  ")[0] if provider else st.selected_provider_id
            _center(0, f" {pname} — choose a model ", bold=True)
            models = provider[2] if provider else []
            if models:
                _draw_list(models, st.model_cursor, st.model_scroll, 2)
            else:
                _put(2, "No models detected for this provider.")
                hint_row = 4
                is_ollama = st.selected_provider_id == "llm_ollama"
                if is_ollama:
                    _put(hint_row, "Ollama must be installed and running:")
                    _put(hint_row + 1, "    https://ollama.com/download")
                    hint_row += 3
                else:
                    _put(hint_row, "Start the provider service or configure it,")
                    _put(hint_row + 1, "then press [R] to refresh.")
                    hint_row += 3
                action_row = min(hint_row, box_h - 5)
                actions = (
                    [
                        "↺  Refresh model list",
                        "⬇  Pull a model (ollama pull…)",
                        "✏  Enter model ID manually",
                    ]
                    if is_ollama
                    else ["↺  Refresh model list", "✏  Enter model ID manually"]
                )
                for i, action in enumerate(actions):
                    sel = st.model_cursor == i
                    _put(action_row + i, ("▶ " if sel else "  ") + action, hl=sel)
            if st.error:
                _put(box_h - 3, st.error)
            _center(box_h - 2, "[↑↓] choose    [R] refresh    [Enter] select    [Esc] back")

        elif st.step == "model_input":
            provider = next((p for p in providers if p[0] == st.selected_provider_id), None)
            pname = provider[1].split("  ")[0] if provider else st.selected_provider_id
            _center(0, f" {pname} — enter model ID ", bold=True)
            _put(2, "Type the model ID exactly as shown by the provider.")
            if st.selected_provider_id == "llm_ollama":
                _put(3, "Example:  llama3    mistral    phi3")
            buf, pos = st.buffer, st.pos
            bar_w = box_w - 8
            offset = max(0, pos - bar_w + 1)
            visible = buf[offset : offset + bar_w]
            cursor_rel = pos - offset
            display = visible[:cursor_rel] + "▌" + visible[cursor_rel:]
            _put(5, f"Model ID:  {display[: bar_w + 1]}", bold=True)
            if st.error:
                _put(7, st.error)
            _center(box_h - 2, "[Enter] confirm    [Esc] back")

        elif st.step == "key":
            _center(0, f" API key for '{st.selected_model_id}' ", bold=True)
            _put(2, f"This model requires an API key  (key name: '{st.key_name}').")
            _put(3, "Get your key from the provider's website or developer console.")
            _put(5, f"Key: {'*' * len(st.buffer)}█")
            if st.error:
                _put(7, st.error)
            _center(box_h - 2, "[Enter] save & continue    [Esc] skip (configure later)")

        elif st.step == "done":
            if st.mode == "copypaste":
                _center(0, " ✓  Copy-paste mode enabled ", bold=True)
                _center(2, "Prompts will be shown and copied to your clipboard.")
                _center(3, "Paste the model response back to continue.")
            else:
                _center(0, " ✓  AI model configured ", bold=True)
                _center(2, f"Model: {st.selected_model_id}")
            _center(box_h - 2, "[Enter / Esc] close")

    # ── Install thread helpers ─────────────────────────────────────────────────

    def install_poll(self) -> None:
        """Called each loop iteration while installing llm. Starts thread, polls result."""
        import threading

        if not isinstance(self._state, AiInstallState):
            return
        st = self._state
        self._install_spinner += 1

        if self._install_thread is None:
            t = threading.Thread(target=self._install_worker, daemon=True)
            self._install_thread = t
            t.start()

        current_lines = list(self._install_output)

        if self._install_returncode is not None:
            self._install_thread = None
            if self._install_returncode == 0:
                self._state = AiInstallState(
                    pending_action=st.pending_action,
                    done=True,
                    lines=current_lines,
                )
            else:
                err = current_lines[-1] if current_lines else "Installation failed"
                self._state = AiInstallState(
                    pending_action=st.pending_action,
                    error=err,
                    lines=current_lines,
                )
            return

        self._state = AiInstallState(
            pending_action=st.pending_action,
            installing=True,
            lines=current_lines,
        )

    def plugin_poll(self) -> None:
        """Called each loop iteration while a plugin is installing or a model is pulling."""
        import dataclasses
        import threading

        if not isinstance(self._state, AiSetupState):
            return
        st = self._state
        if st.step not in ("install_plugin", "ollama_pull") or not st.plugin_installing:
            return

        self._install_spinner += 1

        if self._install_thread is None:
            t = threading.Thread(target=self._install_worker, daemon=True)
            self._install_thread = t
            t.start()

        current_lines = list(self._install_output)

        if self._install_returncode is not None:
            self._install_thread = None
            self._install_command = None
            if self._install_returncode == 0:
                self._state = dataclasses.replace(
                    st,
                    plugin_installing=False,
                    plugin_done=True,
                    plugin_lines=current_lines,
                )
            else:
                err = current_lines[-1] if current_lines else "Installation failed"
                self._state = dataclasses.replace(
                    st,
                    plugin_installing=False,
                    plugin_error=err,
                    plugin_lines=current_lines,
                )
        else:
            self._state = dataclasses.replace(st, plugin_lines=current_lines)

    def _install_worker(self) -> None:
        """Daemon thread: runs pip install or a custom command, streams output."""
        import os
        import subprocess

        cmd = self._install_command or [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-color",
            self._install_package,
        ]

        try:
            import pty

            master_fd, slave_fd = pty.openpty()
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    close_fds=True,
                )
            except Exception:
                os.close(slave_fd)
                raise
            os.close(slave_fd)
            use_pty = True
        except FileNotFoundError:
            self._install_output.append(f"Command not found: {cmd[0]}")
            self._install_returncode = 127
            return
        except (ImportError, OSError):
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
            except FileNotFoundError:
                self._install_output.append(f"Command not found: {cmd[0]}")
                self._install_returncode = 127
                return
            use_pty = False

        buf = b""

        def _flush(sep: bytes) -> None:
            nonlocal buf
            raw = _strip_ansi(buf).decode("utf-8", errors="replace").strip()
            buf = b""
            if not raw:
                return
            if sep == b"\r":
                if self._install_output:
                    self._install_output[-1] = raw
                else:
                    self._install_output.append(raw)
            else:
                self._install_output.append(raw)

        if use_pty:
            while True:
                try:
                    chunk = os.read(master_fd, 256)
                except OSError:
                    break
                if not chunk:
                    break
                for byte in chunk:
                    b = bytes([byte])
                    if b in (b"\r", b"\n"):
                        _flush(b)
                    else:
                        buf += b
            try:
                os.close(master_fd)
            except OSError:
                pass
        else:
            assert proc.stdout is not None
            while True:
                b = proc.stdout.read(1)
                if not b:
                    break
                if b in (b"\r", b"\n"):
                    _flush(b)
                else:
                    buf += b

        _flush(b"\n")
        proc.wait()
        self._install_returncode = proc.returncode


def _strip_ansi(data: bytes) -> bytes:
    import re

    return re.sub(rb"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", b"", data)


def run_ai_config_screen(lang: str = "en") -> None:  # noqa: ARG001
    """Launch the AI model configuration wizard (curses wrapper entry point)."""
    curses.wrapper(_ai_config_main, lang)


def _ai_config_main(stdscr: curses.window, lang: str) -> None:  # noqa: ARG001
    try:
        curses.start_color()
        curses.use_default_colors()
        from .nav.draw import _init_colors

        _init_colors()
    except curses.error:
        pass
    wizard = AiConfigWizard()
    wizard.run(stdscr)
