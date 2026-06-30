"""Prompt templates for all AI features in ster.

Each template uses string.Template substitution ($variable).
Keep this file free of Python logic — plain text only.
"""

from string import Template

# ── Task identifiers ──────────────────────────────────────────────────────────

SUGGEST_CONCEPT_NAMES = "suggest_concept_names"
SUGGEST_ALT_LABELS = "suggest_alt_labels"
SUGGEST_DEFINITION = "suggest_definition"

ALL_TASKS = [
    SUGGEST_CONCEPT_NAMES,
    SUGGEST_ALT_LABELS,
    SUGGEST_DEFINITION,
]

# ── Templates ─────────────────────────────────────────────────────────────────

TMPL_SUGGEST_CONCEPT_NAMES = Template("""\
Optimize the "$taxonomy_name" taxonomy by proposing up to $n \
$scope_phrase. ALL labels must be written in $lang — \
do not use any other language. Focus on concise noun phrases (2–5 words) \
that are mutually exclusive, collectively exhaustive at this level, and \
drawn from established domain terminology. Only include labels that are \
genuinely relevant and distinct — return fewer than $n if appropriate.
${taxonomy_description_line}${parent_line}$exclude_hint
- Prioritize broad, fundamental concepts over narrow, specific ones.
- Capitalise only the first word (sentence case), unless the term is \
a proper noun or acronym.
- Do NOT translate the taxonomy name or parent label.
- Do NOT add definitions, scope notes, numbers, bullets, or any \
explanation.

Rank suggestions from most fundamental to most specific.

Reply with ONLY the labels in $lang, one per line (no more than $n).\
""")

TMPL_SUGGEST_ALT_LABELS = Template("""\
Optimize the "$taxonomy_name" taxonomy by proposing up to 5 alternative \
labels (skos:altLabel) for the concept "$pref_label". \
ALL labels must be written in $lang — do not use any other language.
${taxonomy_description_line}${concept_definition_line}
Include synonyms, acronyms, variant spellings, and common alternative \
phrasings. Each label must be distinct from the preferred label and \
shorter than 60 characters. \
Do NOT add definitions, numbers, bullets, or any explanation.

Reply with ONLY the alternative labels in $lang, one per line.\
""")

TMPL_SUGGEST_DEFINITION = Template("""\
Optimize the "$taxonomy_name" taxonomy by writing a concise \
skos:definition for the concept "$pref_label". \
The definition MUST be written in $lang — do not use any other language.
${taxonomy_description_line}${parent_line}
Write one paragraph of 1–3 sentences that clearly differentiates this \
concept from its siblings at the same level. \
Do not begin with the concept name (avoid "X is a …"). \
Do not include bullets, lists, or headings.

Reply with ONLY the definition text in $lang.\
""")
