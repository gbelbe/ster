"use strict";
// The language loader (i18n.js). Run: node --test agent-app/tests
const test = require("node:test");
const assert = require("node:assert/strict");

const EN = { _name: "English", hello: "Hello {name}", only_en: "only English", "n_one": "{count} thing", "n_other": "{count} things", "code.x": "code {v}" };
const FR = { _name: "Français", hello: "Bonjour {name}", "n_one": "{count} chose", "n_other": "{count} choses" };
const FILES = { "/static/locales/en.json": EN, "/static/locales/fr.json": FR };
const fetched = [];

function browser(languages) {
  Object.defineProperty(globalThis, "navigator", { value: { languages }, configurable: true });
  globalThis.document = { documentElement: { lang: "" }, querySelectorAll: () => [] };
  globalThis.fetch = async url => { fetched.push(url); return FILES[url] ? { ok: true, json: async () => FILES[url] } : { ok: false }; };
}
require("../agent_app/static/i18n.js");
const I18n = globalThis.I18n;

test("the first browser language that has a catalog wins", async () => {
  browser(["de-DE", "fr-FR", "en"]);
  assert.equal(await I18n.load(["en", "fr"]), "fr");
  assert.equal(I18n.t("hello", { name: "Ada" }), "Bonjour Ada");
  assert.equal(document.documentElement.lang, "fr");
});

test("with no match it falls back to English", async () => {
  browser(["de", "ja"]);
  assert.equal(await I18n.load(["en", "fr"]), "en");
  assert.equal(I18n.t("hello", { name: "Ada" }), "Hello Ada");
});

test("a region is ignored, only the language counts", async () => {
  browser(["fr-CA"]);
  assert.equal(await I18n.load(["en", "fr"]), "fr");
});

test("the user's own choice beats the browser", async () => {
  browser(["fr"]);
  assert.equal(await I18n.load(["en", "fr"], "en"), "en");
});

test("a choice nobody offers is ignored", async () => {
  browser(["fr"]);
  assert.equal(await I18n.load(["en", "fr"], "xx"), "fr");
});

test("a language without a catalog on offer is never fetched", async () => {
  browser(["de", "en"]);
  fetched.length = 0;
  await I18n.load(["en", "fr"]);
  assert.ok(!fetched.some(u => u.includes("de.json")));
});

test("a key a language lacks is taken from English", async () => {
  browser(["fr"]);
  await I18n.load(["en", "fr"]);
  assert.equal(I18n.t("only_en"), "only English");
});

test("a key nobody has is shown as it is", async () => {
  browser(["en"]);
  await I18n.load(["en"]);
  assert.equal(I18n.t("no.such.key"), "no.such.key");
});

test("an unfetchable catalog falls back to English instead of failing", async () => {
  browser(["fr"]);
  globalThis.fetch = async url => (url.endsWith("fr.json") ? { ok: false } : { ok: true, json: async () => EN });
  await I18n.load(["en", "fr"]);
  assert.equal(I18n.t("hello", { name: "x" }), "Hello x");
});

test("a catalog that throws on fetch falls back to English", async () => {
  browser(["fr"]);
  globalThis.fetch = async url => { if (url.endsWith("fr.json")) throw new Error("offline"); return { ok: true, json: async () => EN }; };
  await I18n.load(["en", "fr"]);
  assert.equal(I18n.t("hello", { name: "x" }), "Hello x");
});

test("placeholders are filled, and an absent one is left visible", async () => {
  browser(["en"]);
  await I18n.load(["en"]);
  assert.equal(I18n.t("hello", {}), "Hello {name}");
  assert.equal(I18n.t("hello"), "Hello {name}");
});

test("plural forms follow the language's own rules", async () => {
  browser(["en"]);
  await I18n.load(["en", "fr"]);
  assert.equal(I18n.t("n", { count: 1 }), "1 thing");
  assert.equal(I18n.t("n", { count: 2 }), "2 things");
  assert.equal(I18n.t("n", { count: 0 }), "0 things");
  browser(["fr"]);
  await I18n.load(["en", "fr"]);
  assert.equal(I18n.t("n", { count: 0 }), "0 chose");      // French counts zero as singular
  assert.equal(I18n.t("n", { count: 2 }), "2 choses");
});

test("a server message is translated by its code, else shown by its own text", async () => {
  browser(["en"]);
  await I18n.load(["en"]);
  assert.equal(I18n.msg({ code: "code.x", params: { v: 7 }, text: "fallback" }), "code 7");
  assert.equal(I18n.msg({ code: "unknown.code", text: "fallback text" }), "fallback text");
  assert.equal(I18n.msg({ code: "unknown.code" }), "unknown.code");
  assert.equal(I18n.msg(null), "");
});

function fakeElement(dataset) {
  const el = { dataset, attrs: {}, textContent: "", setAttribute(k, v) { this.attrs[k] = v; } };
  return el;
}

test("static markup is filled from data attributes", async () => {
  browser(["fr"]);
  await I18n.load(["en", "fr"]);
  const text = fakeElement({ i18n: "hello" }), attrs = fakeElement({ i18nAttr: "title:hello;aria-label:only_en" });
  const root = { querySelectorAll: sel => (sel === "[data-i18n]" ? [text] : [attrs]) };
  I18n.apply(root);
  assert.equal(text.textContent, "Bonjour {name}");
  assert.deepEqual(attrs.attrs, { title: "Bonjour {name}", "aria-label": "only English" });
});

test("the active language is readable", async () => {
  browser(["fr"]);
  await I18n.load(["en", "fr"]);
  assert.equal(I18n.locale, "fr");
});
