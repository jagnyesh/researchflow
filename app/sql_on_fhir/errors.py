"""Errors shared by the SQL-on-FHIR runners."""


class UnsupportedSearchParamError(ValueError):
    """A search param key the runner doesn't map, or a value of an unsupported type.

    A client error: HybridRunner re-raises it instead of falling back to another runner.
    """

    def __init__(self, param_name: str):
        super().__init__(f"Unsupported search parameter: {param_name!r}")
        self.param_name = param_name
