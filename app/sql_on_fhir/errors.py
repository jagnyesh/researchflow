"""Errors shared by the SQL-on-FHIR runners."""


class UnsupportedSearchParamError(ValueError):
    """A search param key the runner doesn't map, or a value of an unsupported type.

    A client error: HybridRunner re-raises it instead of falling back to another runner.
    """

    def __init__(self, param_name: str):
        super().__init__(f"Unsupported search parameter: {param_name!r}")
        self.param_name = param_name


class UnsupportedViewDefinitionError(ValueError):
    """The custom transpiler can't express part of a ViewDefinition (#263).

    Raised in strict mode (HybridRunner's serving fallback) instead of
    emitting NULL or a no-op filter, which turned into a 0 count read as
    real. The message names the FHIRPath construct, never data."""
