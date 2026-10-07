/* Interface language: follows the browser's language list, falls back to English, can be overridden.
 * Catalogs are plain JSON in locales/<lang>.json ({"_name": "Français", "key": "text with {params}"}).
 * Plurals: t("key", {count: n}) looks for key_<one|other|…> (Intl.PluralRules), then key_other, then key.
 * Add a language by dropping a file in locales/; it appears in the language menu on its own. */
(function (root) {
  "use strict";
  const state = { loc: "en", cur: {}, en: {} };
  const getJSON = async url => { try { const r = await fetch(url); return r.ok ? await r.json() : null; } catch { return null; } };

  async function load(available, override) {
    const wanted = [override, ...(navigator.languages || [navigator.language])].filter(Boolean).map(l => String(l).toLowerCase());
    state.en = (await getJSON("/static/locales/en.json")) || {};
    state.loc = "en"; state.cur = state.en;
    for (const w of wanted) {
      const base = w.split("-")[0];
      if (!available.includes(base)) continue;
      state.loc = base; state.cur = base === "en" ? state.en : (await getJSON(`/static/locales/${base}.json`)) || state.en;
      break;
    }
    document.documentElement.lang = state.loc;
    return state.loc;
  }
  function t(key, p) {
    let s;
    if (p && typeof p.count === "number") {
      const rule = new Intl.PluralRules(state.loc).select(p.count);
      s = state.cur[`${key}_${rule}`] ?? state.cur[`${key}_other`] ?? state.en[`${key}_${rule}`] ?? state.en[`${key}_other`];
    }
    s = s ?? state.cur[key] ?? state.en[key];
    if (s == null) return key;  // an unknown key (e.g. free text from an adapter) is shown as it is
    return p ? s.replace(/\{(\w+)\}/g, (m, k) => (p[k] ?? m)) : s;
  }
  /** A message sent by the server: {code, params}; falls back to its English text. */
  const msg = m => m ? (m.code && (state.cur[m.code] ?? state.en[m.code]) != null ? t(m.code, m.params) : (m.text || m.code || "")) : "";
  /** Fills static markup: data-i18n="key" sets the text; data-i18n-attr="placeholder:key;title:key" sets attributes. */
  function apply(rootEl) {
    (rootEl || document).querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
    (rootEl || document).querySelectorAll("[data-i18n-attr]").forEach(el => el.dataset.i18nAttr.split(";").forEach(pair => { const [a, k] = pair.split(":"); el.setAttribute(a, t(k)); }));
  }
  root.I18n = { load, t, msg, apply, get locale() { return state.loc; } };
})(globalThis);
