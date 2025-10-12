from app.mcp.store import FileContextStore


def test_mcp_save_load(tmp_path):
    store = FileContextStore(str(tmp_path))
    store.save("r1", {"k": "v"})
    loaded = store.load("r1")
    assert loaded["k"] == "v"
