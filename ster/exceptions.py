"""Domain exceptions for ster operations."""


class SkostaxError(Exception):
    """Base class for all ster errors."""


class HandleNotFoundError(SkostaxError):
    def __init__(self, handle: str) -> None:
        super().__init__(f"Handle or URI not found: {handle!r}")
        self.handle = handle


class ConceptNotFoundError(SkostaxError):
    def __init__(self, uri: str) -> None:
        super().__init__(f"Concept not found: {uri!r}")
        self.uri = uri


class ConceptAlreadyExistsError(SkostaxError):
    def __init__(self, uri: str) -> None:
        super().__init__(f"Concept already exists: {uri!r}")
        self.uri = uri


class SchemeNotFoundError(SkostaxError):
    def __init__(self, uri: str) -> None:
        super().__init__(f"Concept scheme not found: {uri!r}")
        self.uri = uri


class HasChildrenError(SkostaxError):
    def __init__(self, uri: str, count: int) -> None:
        super().__init__(
            f"Concept {uri!r} has {count} child(ren). Use cascade=True to remove them."
        )
        self.uri = uri
        self.count = count


class CircularHierarchyError(SkostaxError):
    def __init__(self, uri: str, ancestor_uri: str) -> None:
        super().__init__(
            f"Moving {uri!r} under {ancestor_uri!r} would create a circular hierarchy."
        )


class RelatedHierarchyConflictError(SkostaxError):
    def __init__(self, uri_a: str, uri_b: str) -> None:
        super().__init__(
            f"Cannot add skos:related between {uri_a!r} and {uri_b!r}: "
            "they are already in a hierarchical relationship."
        )


class ClassNotFoundError(SkostaxError):
    def __init__(self, uri: str) -> None:
        super().__init__(f"OWL class not found: {uri!r}")
        self.uri = uri


class URIAlreadyExistsError(SkostaxError):
    def __init__(self, uri: str) -> None:
        super().__init__(f"URI already exists in taxonomy: {uri!r}")
        self.uri = uri
