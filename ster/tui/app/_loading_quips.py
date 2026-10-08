"""A line of light commentary under the loading spinner, picked by what the loader is doing."""

from __future__ import annotations

QUIP_EVERY = (
    30  # spinner frames (about 0.12 s each) a sentence stays up before the next one rolls in
)

# (start of the step's message, sentences for it). The first entry whose start matches wins, so a longer message
# that begins like a shorter one ("Building browser tree" / "Building browser") comes before it.
_BY_STEP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Starting", ("Warming up the hamsters.", "Opening the file. Politely.")),
    (
        "Parsing RDF",
        ("Reading Turtle. Not the reptile, sadly.", "Counting triples, three at a time."),
    ),
    (
        "Building model",
        ("Turning triples into things you can click.", "Giving every URI a personality."),
    ),
    (
        "Assigning handles",
        ("Handing every entity a nametag.", "Short names for long URIs: the great shortening."),
    ),
    (
        "Updating cache",
        (
            "Packing it all up so next time takes seconds, not a coffee.",
            "Writing the cache. Future you says thanks.",
        ),
    ),
    (
        "Loaded from cache",
        (
            "Straight from the cache. The easy part, enjoy it.",
            "Cache hit. Suspiciously quick, we know.",
        ),
    ),
    ("Ready", ("Ta-da.", "All set. The spinner can rest.")),
    (
        "Reading the editable file",
        (
            "Memorising your schema before anyone moves the furniture.",
            "Noting which classes are yours, so nobody edits the neighbours.",
        ),
    ),
    (
        "Reading context",
        (
            "Reading Turtle, one prefix at a time. Turtles are not famous for their speed.",
            "rdflib parses in pure Python. It is doing its best.",
            "Each file is read once now. We learnt our lesson.",
            "Big files take time. Small files take time too, just less.",
        ),
    ),
    (
        "Merging context",
        (
            "Introducing every class to its neighbours.",
            "Teaching the files to share one graph.",
            "Keeping the read-only files read-only, as promised.",
            "Skipping duplicates, so the triples don't argue at dinner.",
        ),
    ),
    (
        "Building navigation index",
        ("Drawing the map before the tour.", "Alphabetising the universe."),
    ),
    (
        "Indexing individuals",
        (
            "Sorting every individual into its class drawer.",
            "Counting individuals. Yes, all of them.",
        ),
    ),
    (
        "Configuring browser",
        ("Adjusting the chairs and the mirrors.", "Tightening the bolts on the tree view."),
    ),
    (
        "Building properties",
        ("Listing what everything can be, have and do.", "Properties: the verbs of the ontology."),
    ),
    (
        "Building browser tree",
        ("Growing the tree, one branch at a time.", "Planting the tree. No watering needed."),
    ),
    ("Building ontology tree", ("Branching out.", "Hanging each class on the right branch.")),
    ("Building browser", ("Laying out the panels.", "Arranging the panes like a tidy desk.")),
    (
        "Finalizing browser",
        ("Last polish on the pixels.", "Putting the cursor where you would expect it."),
    ),
)
_ELSEWHERE = (
    "Still working. Thank you for your patience.",
    "Good things come to those who wait for the cache.",
)


def quip_for(message: str, tick: int) -> str:
    """The sentence for the loader step *message*, rolling to the next one every time *tick* goes up by one."""
    sentences = next((s for start, s in _BY_STEP if message.startswith(start)), _ELSEWHERE)
    return sentences[tick % len(sentences)]
