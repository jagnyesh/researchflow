import json
import os
from pathlib import Path


class FileContextStore:
    def __init__(self, dirpath: str | None = None):
        self.dir = Path(dirpath or "./mcp_contexts")
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, request_id: str) -> Path:
        """`<dir>/<request_id>.json`, or ValueError unless it stays directly in `dir`.

        request_id arrives in the POST /mcp/context body (#223). realpath +
        startswith is the guard shape CodeQL recognizes (ADR 0037). A resolved
        path that differs from the joined one is a symlink, refused even within
        the directory.
        """
        if (
            not isinstance(request_id, str)
            or request_id in ("", ".", "..")
            or any(c in request_id for c in ("/", "\\", "\x00"))
        ):
            raise ValueError("Unsafe MCP context request_id")
        base_real = os.path.realpath(self.dir)
        joined = os.path.join(base_real, f"{request_id}.json")
        full = os.path.realpath(joined)
        if not full.startswith(base_real + os.sep) or full != joined:
            raise ValueError("Unsafe MCP context request_id")
        return Path(full)

    def save(self, request_id: str, context: dict):
        path = self._path_for(request_id)
        path.write_text(json.dumps(context))

    def load(self, request_id: str) -> dict | None:
        try:
            path = self._path_for(request_id)
        except ValueError:
            return None
        if not path.exists():
            return None
        return json.loads(path.read_text())
