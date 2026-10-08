/* Pure text helpers for the page: HTML escaping, a small markdown renderer, SPARQL highlighting.
 * Everything an agent writes passes through here before it reaches the DOM, so each function escapes first.
 * No DOM access, so it is tested under node. */
(function (root) {
  "use strict";
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ================= markdown (small, escaped first) ================= */
  function inline(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }
  function md(src) {
    const L = String(src ?? "").replace(/\r/g, "").split("\n"); const out = []; let i = 0;
    const block = l => /^(```|#{1,4}\s|\s*[-*]\s+|\s*\d+[.)]\s+|\s*\|)/.test(l);
    while (i < L.length) {
      const l = L[i]; let m;
      if (/^```/.test(l)) { const c = []; i++; while (i < L.length && !/^```/.test(L[i])) c.push(L[i++]); i++; out.push(`<pre><code>${esc(c.join("\n"))}</code></pre>`); continue; }
      if (/^\s*\|.*\|\s*$/.test(l) && /^\s*\|[\s:|-]+\|\s*$/.test(L[i + 1] || "")) {
        const cells = r => r.trim().replace(/^\||\|$/g, "").split("|").map(x => x.trim());
        const head = cells(l); i += 2; const rows = [];
        while (i < L.length && /^\s*\|.*\|\s*$/.test(L[i])) rows.push(cells(L[i++]));
        out.push(`<div class="tbl"><table><thead><tr>${head.map(h => `<th>${inline(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
        continue;
      }
      if ((m = l.match(/^(#{1,4})\s+(.*)/))) { out.push(`<h${m[1].length + 2}>${inline(m[2])}</h${m[1].length + 2}>`); i++; continue; }
      if (/^\s*[-*]\s+/.test(l)) { const it = []; while (i < L.length && /^\s*[-*]\s+/.test(L[i])) it.push(L[i++].replace(/^\s*[-*]\s+/, "")); out.push(`<ul>${it.map(x => `<li>${inline(x)}</li>`).join("")}</ul>`); continue; }
      if (/^\s*\d+[.)]\s+/.test(l)) { const it = []; while (i < L.length && /^\s*\d+[.)]\s+/.test(L[i])) it.push(L[i++].replace(/^\s*\d+[.)]\s+/, "")); out.push(`<ol>${it.map(x => `<li>${inline(x)}</li>`).join("")}</ol>`); continue; }
      if (!l.trim()) { i++; continue; }
      const p = []; while (i < L.length && L[i].trim() && !block(L[i])) p.push(L[i++]); if (!p.length) p.push(L[i++]);
      out.push(`<p>${inline(p.join(" "))}</p>`);
    }
    return out.join("");
  }

  /* ================= SPARQL highlighting ================= */
  const KW = new Set("PREFIX BASE SELECT DISTINCT REDUCED WHERE FILTER OPTIONAL UNION GROUP BY ORDER HAVING LIMIT OFFSET COUNT SUM AVG MIN MAX AS ASK CONSTRUCT DESCRIBE VALUES BIND NOT EXISTS IN SERVICE MINUS DESC ASC REGEX STR LANG STRSTARTS STRENDS CONTAINS LCASE UCASE SAMPLE GROUP_CONCAT IF COALESCE A".split(" "));
  function sparql(q) {
    const re = /(#[^\n]*)|("(?:[^"\\\n]|\\.)*"(?:@[\w-]+|\^\^\S+)?)|(<[^>\s]*>)|([?$][\w]+)|([A-Za-z_][\w-]*:[\w.-]*)|([A-Za-z_]\w*)/g;
    let out = "", last = 0, m; q = String(q ?? "");
    while ((m = re.exec(q))) {
      out += esc(q.slice(last, m.index)); last = re.lastIndex;
      const t = m[0];
      if (m[1]) out += `<span class="t-cmt">${esc(t)}</span>`;
      else if (m[2]) out += `<span class="t-str">${esc(t)}</span>`;
      else if (m[3] || m[5]) out += `<span class="t-iri">${esc(t)}</span>`;
      else if (m[4]) out += `<span class="t-var">${esc(t)}</span>`;
      else if (m[6] && KW.has(t.toUpperCase())) out += `<span class="t-kw">${esc(t)}</span>`;
      else out += esc(t);
    }
    return out + esc(q.slice(last));
  }


  /* ================= what a call looks for, in plain words ================= */
  /* The question an agent gave for a step: the one ster recorded in its trace of the call (from MCP metadata or from
   * the call's "question" argument), else the argument itself, which the call's own input still carries. */
  function toolQuestion(tool) {
    const asked = tool.input && typeof tool.input.question === "string" ? tool.input.question.trim() : "";
    return (tool.trace && tool.trace.agent_question) || asked || "";
  }
  /* one line for a step: the distinct questions of its calls */
  function stepQuestion(tools) { return [...new Set(tools.map(toolQuestion).filter(Boolean))].join(" · "); }

  /* ================= a call that failed ================= */
  /* Why a call failed, from what ster recorded in its trace (a failed step: code, message, kind of fault, traceback)
   * or, without a trace, from the call's own result: a result flagged as an error, or one whose JSON says "error".
   * null when the call did not fail. A failed call used to draw nothing at all. */
  function resultJson(text) { try { const v = JSON.parse(text); return v && typeof v === "object" ? v : null; } catch { return null; } }
  function toolFailure(tool) {
    const step = ((tool.trace && tool.trace.steps) || []).find(x => x.status === "failed" || x.error_message);
    if (step) return { code: step.error_code || "", message: step.error_message || "", kind: step.error_type || "", traceback: step.traceback || "" };
    const result = tool.result;
    if (!result) return null;
    const body = resultJson(result.text);
    if (!result.is_error && !(body && body.error)) return null;
    return {
      code: body && typeof body.error === "string" ? body.error : "",
      message: (body && (body.message || body.error)) || String(result.text || ""),
      kind: (body && body.error_type) || "",
      traceback: (body && body.traceback) || "",
    };
  }
  /* the failure as markup; *labels* are the page's own words for its parts, everything else is escaped */
  function failureHtml(f, labels) {
    const code = f.code ? ` <code>${esc(f.code)}</code>` : "";
    const kind = f.kind ? `<div class="kv">${esc(labels.kind)} <code>${esc(f.kind)}</code></div>` : "";
    const where = f.traceback ? `<details><summary>${esc(labels.where)}</summary><pre>${esc(f.traceback)}</pre></details>` : "";
    return `<div class="failure"><div class="label">${esc(labels.failed)}${code}</div><div class="err"><span>✕</span><div><b>${esc(f.message)}</b>${kind}${where}</div></div></div>`;
  }

  /* ================= a lost connection to ster ================= */
  /* An agent keeps one connection to ster for a whole conversation. When ster has been restarted since the
   * conversation's last answer, that connection is gone: the agent says ster is disconnected while the page, which
   * asks ster afresh, shows it connected. *sterStarted* is the start time of the ster answering now. */
  function connectionLost(turns, sterStarted) {
    const last = [...(turns || [])].reverse().find(t => t.ster_started);
    return !!(last && sterStarted && last.ster_started !== sterStarted);
  }

  const api = { esc, md, sparql, toolQuestion, stepQuestion, toolFailure, failureHtml, connectionLost };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Render = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
