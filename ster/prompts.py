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
You are a professional taxonomist and subject-matter expert building a \
SKOS controlled vocabulary.

Taxonomy: "$taxonomy_name"
${taxonomy_description_line}${parent_line}Language: $lang

Task: Propose up to $n $scope_phrase for the position described above. \
Only include labels that are genuinely relevant and distinct — if fewer \
than $n are appropriate, return only those.
$exclude_hint
Guidelines:
- Each label must be a concise noun phrase (2–5 words preferred).
- Labels must be mutually exclusive and collectively exhaustive at this \
level of the hierarchy.
- Use the vocabulary register appropriate for "$taxonomy_name" \
(professional/technical if the domain is specialised; plain language if \
the taxonomy is general-purpose).
- Prefer established terminology from the relevant domain; avoid \
invented compound words.
- Capitalise only the first word (sentence case), unless a term is a \
proper noun or acronym.
- Labels must be in language '$lang'. Do NOT translate the taxonomy name \
or parent label.
- Rank suggestions from broadest/most fundamental to narrowest/most \
specific.
- Do NOT add definitions, scope notes, numbers, bullets, or any \
explanation.

Reply with ONLY the labels, one per line (no more than $n).\
""")

TMPL_SUGGEST_ALT_LABELS = Template("""\
You are a professional taxonomist building a SKOS controlled vocabulary.

Taxonomy: "$taxonomy_name"
${taxonomy_description_line}Preferred label: "$pref_label"
Language: $lang

Task: Suggest up to 5 alternative labels (skos:altLabel) for this concept.

Guidelines:
- Include synonyms, acronyms, variant spellings, and common alternative phrasings.
- Each label must be shorter than 60 characters.
- Do NOT repeat the preferred label.
- Labels must be in language '$lang'.
- Do NOT add definitions, numbers, bullets, or any explanation.

Reply with ONLY the alternative labels, one per line.\
""")

TMPL_SUGGEST_DEFINITION = Template("""\
You are a professional taxonomist building a SKOS controlled vocabulary.

Taxonomy: "$taxonomy_name"
${taxonomy_description_line}${parent_line}Concept: "$pref_label"
Language: $lang

Task: Write a concise SKOS definition (skos:definition) for this concept \
in language '$lang'.

Guidelines:
- One paragraph, 1–3 sentences.
- Must differentiate this concept from siblings at the same level.
- Use the vocabulary register appropriate for "$taxonomy_name".
- Do NOT start with the concept name itself (avoid "X is a …").
- Do NOT include bullets, lists, or section headings.

Reply with ONLY the definition text, nothing else.\
""")
