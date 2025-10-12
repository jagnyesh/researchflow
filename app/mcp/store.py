import json
from pathlib import Path


class FileContextStore:
    def __init__(self, dirpath: str | None = None):
        self.dir = Path(dirpath or "./mcp_contexts")
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, request_id: str, context: dict):
        path = self.dir / f"{request_id}.json"
        path.write_text(json.dumps(context))

    def load(self, request_id: str) -> dict | None:
        path = self.dir / f"{request_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())
