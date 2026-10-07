"""The interface text lives in locales/*.json. These tests keep the catalogs complete and the core agent-agnostic."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
WEB = APP / "agent_app"
STATIC = WEB / "static"
CATALOGS = {p.stem: json.loads(p.read_text()) for p in sorted((STATIC / "locales").glob("*.json"))}
CORE = [WEB / n for n in ("server.py", "runner.py", "rules.py", "native.py")] + [
    STATIC / n for n in ("viz.js", "i18n.js", "render.js", "index.html")
]
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|\s)//.*$", "", text)


class Catalogs(unittest.TestCase):  # noqa: V102
    def test_english_exists_it_is_the_fallback(self):
        self.assertIn("en", CATALOGS)

    def test_every_language_has_the_same_keys(self):
        base = set(CATALOGS["en"])
        for lang, cat in CATALOGS.items():
            self.assertEqual(base - set(cat), set(), f"{lang} is missing keys")
            self.assertEqual(set(cat) - base, set(), f"{lang} has keys English lacks")

    def test_every_language_names_itself(self):
        for lang, cat in CATALOGS.items():
            self.assertTrue(cat.get("_name"), lang)

    def test_placeholders_match_across_languages(self):
        for key, text in CATALOGS["en"].items():
            for lang, cat in CATALOGS.items():
                self.assertEqual(
                    set(PLACEHOLDER.findall(cat[key])),
                    set(PLACEHOLDER.findall(text)),
                    f"{lang}:{key}",
                )

    def test_no_empty_text(self):
        for lang, cat in CATALOGS.items():
            self.assertEqual([k for k, v in cat.items() if not str(v).strip()], [], lang)

    def test_a_plural_key_has_its_other_form(self):
        for lang, cat in CATALOGS.items():
            for key in cat:
                if key.endswith("_one"):
                    self.assertTrue(key[:-4] + "_other" in cat, f"{lang}:{key} has no _other form")


class KeysInCode(unittest.TestCase):  # noqa: V102
    """Every key the code asks for exists. Keys built at run time are listed here so they are checked too."""

    DYNAMIC = (
        ["hist." + g for g in ("today", "yesterday", "week", "older")]
        + [
            "kind." + k
            for k in ("kpi", "bar", "donut", "line", "grouped", "stacked", "scatter", "table")
        ]
        + ["tok." + k for k in ("input", "output", "cache_read", "cache_write")]
        + [f"ex.{n}" for n in range(1, 5)]
        + [f"ex.{n}.tag" for n in range(1, 5)]
        + ["lastcap." + k for k in ("stream_steps", "token_usage", "cost", "resume", "sparql_rows")]
    )

    def has(self, key):
        en = CATALOGS["en"]
        return key in en or key + "_one" in en or key + "_other" in en

    def test_static_keys_used_by_the_page_and_the_chart_logic(self):
        used = set(
            re.findall(r'\btx\("([a-z_]+\.[a-z_0-9.]+)"', (STATIC / "index.html").read_text())
        )
        used |= set(re.findall(r'\bT\("([a-z_]+\.[a-z_0-9.]+)"', (STATIC / "viz.js").read_text()))
        for attr in re.findall(
            r'data-i18n(?:-attr)?="([^"]+)"', (STATIC / "index.html").read_text()
        ):
            used |= {part.split(":")[-1] for part in attr.split(";")}
        used |= set(re.findall(r'data-ask="([a-z_.]+)"', (STATIC / "index.html").read_text()))
        self.assertGreater(len(used), 100)
        self.assertEqual(sorted(k for k in used if not self.has(k)), [])

    def test_keys_built_at_run_time_exist(self):
        self.assertEqual(sorted(k for k in self.DYNAMIC if not self.has(k)), [])

    def test_codes_the_server_and_runner_can_send_exist(self):
        codes = set()
        for name in ("server.py", "runner.py"):
            codes |= set(re.findall(r'"((?:reason|err|prob)\.[a-z_]+)"', (WEB / name).read_text()))
        self.assertGreaterEqual(len(codes), 6)
        self.assertEqual(sorted(c for c in codes if not self.has(c)), [])

    def test_no_catalog_key_is_unused(self):
        code = "".join(
            p.read_text()
            for p in (
                STATIC / "index.html",
                STATIC / "viz.js",
                WEB / "server.py",
                WEB / "runner.py",
            )
        )
        unused = [
            k
            for k in CATALOGS["en"]
            if not k.startswith("_")
            and re.sub(r"_(one|other)$", "", k) not in code
            and k not in self.DYNAMIC
            and not k.startswith(("hist.today", "ex."))
        ]
        self.assertEqual(unused, [])


class CoreStaysAgnostic(unittest.TestCase):  # noqa: V102
    NAMES = re.compile(
        r"claude|anthropic|opencode|codex|gemini|copilot|cursor-agent", re.I
    )  # agent products

    def test_no_agent_is_named_in_the_core(self):
        for path in CORE + sorted((STATIC / "locales").glob("*.json")):
            hits = self.NAMES.findall(path.read_text())
            self.assertEqual(hits, [], f"{path.name} names an agent")

    def test_model_server_protocols_are_named_only_by_the_file_that_speaks_them(self):
        # native.py speaks Ollama's API and the OpenAI-compatible one; nothing else needs to know either name
        protocol = re.compile(r"ollama|openai", re.I)
        for path in CORE:
            if path.name != "native.py":
                self.assertEqual(protocol.findall(path.read_text()), [], path.name)

    def test_the_project_is_not_named_in_the_core(self):
        for path in CORE:
            self.assertNotRegex(path.read_text().lower(), r"adeo", path.name)

    def test_no_text_is_written_into_the_page_in_a_language(self):
        accented = re.compile(r"[àâçéèêëîïôûùüÿœ]", re.I)
        for path in (STATIC / "index.html", STATIC / "viz.js"):
            lines = [
                ln for ln in strip_comments(path.read_text()).splitlines() if "TIMEISH" not in ln
            ]  # a deliberate multilingual word list
            self.assertEqual(
                [ln.strip()[:60] for ln in lines if accented.search(ln)], [], path.name
            )

    def test_no_untranslated_words_hide_in_code_or_css(self):
        french = re.compile(
            r"\b(hors ligne|aucun|aucune|fermer|erreur|chargement|lignes?|étapes?|voir|envoyer|supprimer)\b",
            re.I,
        )
        for path in (STATIC / "index.html", STATIC / "viz.js"):
            code = strip_comments(path.read_text())
            self.assertEqual(french.findall(code), [], path.name)

    def test_css_generated_text_comes_from_the_page_not_from_a_language(self):
        for text in re.findall(r'content:\s*"([^"]*)"', (STATIC / "index.html").read_text()):
            self.assertNotRegex(text, r"[A-Za-z]{3,}", f"CSS content {text!r} is a hard-coded word")

    def test_the_agent_specific_files_live_in_the_recipes_folder_only(self):
        names = {p.name for p in WEB.iterdir() if p.is_file()}
        self.assertEqual({n for n in names if self.NAMES.search(n)}, set())
        self.assertTrue(
            any(
                self.NAMES.search(p.read_text())
                for p in (WEB / "recipes").iterdir()
                if p.suffix in (".json", ".py")
            )
        )


if __name__ == "__main__":
    unittest.main()
