"""Built-in preset SPARQL queries and editor keyword list.

Extend ``PRESET_QUERIES`` to add domain-specific or AI-generated queries to
the preset menu; ``SPARQL_KEYWORDS`` feeds editor autocomplete.
"""

from __future__ import annotations

from ._types import PresetQuery

_PREFIXES = """\
PREFIX skos:    <http://www.w3.org/2004/02/skos/core#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX owl:     <http://www.w3.org/2002/07/owl#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX xsd:     <http://www.w3.org/2001/XMLSchema#>
"""


SPARQL_KEYWORDS: list[str] = [
    # Query forms
    "SELECT",
    "CONSTRUCT",
    "DESCRIBE",
    "ASK",
    # Clauses
    "WHERE",
    "PREFIX",
    "BASE",
    "FROM",
    "FROM NAMED",
    "GRAPH",
    "OPTIONAL",
    "UNION",
    "FILTER",
    "BIND",
    "VALUES",
    "GROUP BY",
    "HAVING",
    "ORDER BY",
    "DESC",
    "ASC",
    "LIMIT",
    "OFFSET",
    "DISTINCT",
    "REDUCED",
    "MINUS",
    "SERVICE",
    "SILENT",
    "AS",
    "IN",
    "NOT IN",
    "EXISTS",
    "NOT EXISTS",
    # Update
    "INSERT",
    "INSERT DATA",
    "DELETE",
    "DELETE DATA",
    "DELETE WHERE",
    "WITH",
    "USING",
    "USING NAMED",
    "LOAD",
    "CLEAR",
    "DROP",
    "CREATE",
    "ADD",
    "MOVE",
    "COPY",
    "NAMED",
    "ALL",
    "UNDEF",
    # Built-in functions
    "STR",
    "LANG",
    "LANGMATCHES",
    "DATATYPE",
    "BOUND",
    "IRI",
    "URI",
    "BNODE",
    "RAND",
    "ABS",
    "CEIL",
    "FLOOR",
    "ROUND",
    "CONCAT",
    "STRLEN",
    "UCASE",
    "LCASE",
    "ENCODE_FOR_URI",
    "CONTAINS",
    "STRSTARTS",
    "STRENDS",
    "STRBEFORE",
    "STRAFTER",
    "YEAR",
    "MONTH",
    "DAY",
    "HOURS",
    "MINUTES",
    "SECONDS",
    "TIMEZONE",
    "TZ",
    "NOW",
    "UUID",
    "STRUUID",
    "MD5",
    "SHA1",
    "SHA256",
    "SHA384",
    "SHA512",
    "COALESCE",
    "IF",
    "STRLANG",
    "STRDT",
    "SAMETERM",
    "ISIRI",
    "ISURI",
    "ISBLANK",
    "ISLITERAL",
    "ISNUMERIC",
    "REGEX",
    "SUBSTR",
    "REPLACE",
    # Aggregates
    "COUNT",
    "SUM",
    "MIN",
    "MAX",
    "AVG",
    "SAMPLE",
    "GROUP_CONCAT",
    "SEPARATOR",
    # Booleans / special
    "true",
    "false",
    "a",
]


PRESET_QUERIES: list[PresetQuery] = [
    PresetQuery(
        label="All concepts",
        description="Every concept with its preferred label.",
        sparql=_PREFIXES
        + """\
SELECT ?concept ?label
WHERE {
  ?concept a skos:Concept ;
           skos:prefLabel ?label .
}
ORDER BY ?label
""",
    ),
    PresetQuery(
        label="Missing definitions",
        description="Concepts that have no skos:definition.",
        sparql=_PREFIXES
        + """\
SELECT ?concept ?label
WHERE {
  ?concept a skos:Concept ;
           skos:prefLabel ?label .
  FILTER NOT EXISTS { ?concept skos:definition ?def }
}
ORDER BY ?label
""",
    ),
    PresetQuery(
        label="Missing alt labels",
        description="Concepts that have no skos:altLabel.",
        sparql=_PREFIXES
        + """\
SELECT ?concept ?label
WHERE {
  ?concept a skos:Concept ;
           skos:prefLabel ?label .
  FILTER NOT EXISTS { ?concept skos:altLabel ?alt }
}
ORDER BY ?label
""",
    ),
    PresetQuery(
        label="Concepts per scheme",
        description="Count of concepts in each ConceptScheme.",
        sparql=_PREFIXES
        + """\
SELECT ?scheme (COUNT(?concept) AS ?count)
WHERE {
  ?concept a skos:Concept ;
           skos:inScheme ?scheme .
}
GROUP BY ?scheme
ORDER BY DESC(?count)
""",
    ),
    PresetQuery(
        label="Top concepts",
        description="Concepts directly attached to a scheme root.",
        sparql=_PREFIXES
        + """\
SELECT ?concept ?label ?scheme
WHERE {
  ?concept a skos:Concept ;
           skos:prefLabel ?label ;
           skos:topConceptOf ?scheme .
}
ORDER BY ?scheme ?label
""",
    ),
    PresetQuery(
        label="Hierarchy",
        description="Parent → child pairs via skos:narrower.",
        sparql=_PREFIXES
        + """\
SELECT ?parent ?parentLabel ?child ?childLabel
WHERE {
  ?parent skos:narrower ?child .
  ?parent skos:prefLabel ?parentLabel .
  ?child  skos:prefLabel ?childLabel .
}
ORDER BY ?parentLabel ?childLabel
""",
    ),
    PresetQuery(
        label="Alt labels",
        description="All alternative labels per concept.",
        sparql=_PREFIXES
        + """\
SELECT ?concept ?prefLabel ?altLabel
WHERE {
  ?concept a skos:Concept ;
           skos:prefLabel ?prefLabel ;
           skos:altLabel  ?altLabel .
}
ORDER BY ?prefLabel
""",
    ),
    PresetQuery(
        label="Related concepts",
        description="All skos:related pairs.",
        sparql=_PREFIXES
        + """\
SELECT ?a ?aLabel ?b ?bLabel
WHERE {
  ?a skos:related ?b .
  ?a skos:prefLabel ?aLabel .
  ?b skos:prefLabel ?bLabel .
}
ORDER BY ?aLabel
""",
    ),
    PresetQuery(
        label="Scheme metadata",
        description="Title, creator and language of each scheme.",
        sparql=_PREFIXES
        + """\
SELECT ?scheme ?title ?creator ?lang
WHERE {
  ?scheme a skos:ConceptScheme .
  OPTIONAL { ?scheme skos:prefLabel   ?title   }
  OPTIONAL { ?scheme dcterms:creator  ?creator }
  OPTIONAL { ?scheme dcterms:language ?lang    }
}
ORDER BY ?scheme
""",
    ),
    PresetQuery(
        label="Scope notes",
        description="All skos:scopeNote values.",
        sparql=_PREFIXES
        + """\
SELECT ?concept ?label ?note
WHERE {
  ?concept a skos:Concept ;
           skos:prefLabel ?label ;
           skos:scopeNote ?note .
}
ORDER BY ?label
""",
    ),
]
