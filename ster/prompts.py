"""Prompt templates for all AI features in ster.

Each template uses string.Template substitution ($variable).
Keep this file free of Python logic — plain text only.
"""

from string import Template

# ── Task identifiers ──────────────────────────────────────────────────────────

SUGGEST_CONCEPT_NAMES = "suggest_concept_names"

ALL_TASKS = [
    SUGGEST_CONCEPT_NAMES,
]

# ── Templates ─────────────────────────────────────────────────────────────────

TMPL_SUGGEST_CONCEPT_NAMES = Template("""\
You are a professional taxonomist and subject-matter expert building a \
SKOS controlled vocabulary.

Taxonomy: "$taxonomy_name"
${taxonomy_description_line}${parent_line}Language: $lang

Task: Propose exactly $n $scope_phrase for the position described above.
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

Reply with ONLY the $n labels, one per line.\
""")
