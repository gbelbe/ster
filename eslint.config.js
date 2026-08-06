// Flat ESLint config for ster's browser-side JavaScript assets.
//
// Lints the graph application layer (ster/assets/*.js) and the browser
// extension (kai-extension/*.js). These are plain browser scripts (no bundler,
// no modules) that use the vendored Cytoscape global, so the config declares
// browser + cytoscape globals and keeps the ruleset pragmatic: it catches real
// bugs (undeclared variables, unreachable code) without forcing a refactor of
// the existing IIFE style.

import js from "@eslint/js";
import globals from "globals";

export default [
  {
    // This config file is an ES module and is not part of the browser assets.
    ignores: [
      "node_modules/**",
      ".venv*/**",
      ".uv_cache/**",
      "dist/**",
      "eslint.config.js",
    ],
  },
  js.configs.recommended,
  {
    files: ["**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        cytoscape: "readonly",
        chrome: "readonly",
      },
    },
    rules: {
      // The graph code intentionally swallows errors in best-effort paths
      // (e.g. catch(_){}), and leaves a couple of intentionally-unused catch
      // bindings — these are not bugs.
      "no-empty": ["error", { allowEmptyCatch: true }],
      "no-unused-vars": ["error", { caughtErrors: "none", args: "none" }],
    },
  },
];
