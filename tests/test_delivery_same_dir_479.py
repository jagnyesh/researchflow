"""#479: delivery must not copy extraction's CSVs onto themselves.

Extraction and delivery both build FileStorageService() from the same base
path, so the CSVs are already in the delivery directory. Uses the real
FileStorageService under tmp_path; no database or LLM is touched.
"""

import pandas as pd
import pytest

from app.agents.delivery_agent import DeliveryAgent
from app.services.file_storage import FileStorageService

REQUEST_ID = "REQ-479"
METADATA_FILES = {
    "data_dictionary.txt",
    "qa_report.txt",
    "README.txt",
    "extraction_metadata.json",
}


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DELIVERY_PATH", str(tmp_path))
    return DeliveryAgent()


@pytest.fixture
def package():
    return {
        "data": {"file_paths": []},
        "metadata": {"request_id": REQUEST_ID},
        "documentation": {
            "data_dictionary": {},
            "qa_summary": {"status": "pass", "checks_performed": 0, "checks_passed": 0},
            "extraction_methods": {},
            "citation_info": "",
            "extraction_warnings": [],
        },
    }


@pytest.mark.asyncio
async def test_delivery_after_extraction_in_same_base_path(agent, package, tmp_path):
    # Extraction writes through the same service and base path (env default).
    extraction_storage = FileStorageService()
    csv_path = extraction_storage.save_csv(
        REQUEST_ID, "patients.csv", pd.DataFrame({"patient_id": ["a", "b"]})
    )
    package["data"]["file_paths"] = [csv_path]

    location, csv_filenames = await agent._upload_to_secure_storage(package, REQUEST_ID)

    assert location == str(tmp_path / REQUEST_ID)
    assert csv_filenames == ["patients.csv"]
    delivered = {p.name for p in (tmp_path / REQUEST_ID).iterdir()}
    assert METADATA_FILES <= delivered
    assert (tmp_path / REQUEST_ID / "patients.csv").read_text().startswith("patient_id")


@pytest.mark.asyncio
async def test_delivery_still_copies_csv_from_other_directory(agent, package, tmp_path):
    src_dir = tmp_path / "elsewhere"
    src_dir.mkdir()
    src = src_dir / "labs.csv"
    src.write_text("a\n1\n")
    package["data"]["file_paths"] = [str(src)]

    _, csv_filenames = await agent._upload_to_secure_storage(package, REQUEST_ID)

    assert csv_filenames == ["labs.csv"]
    assert (tmp_path / REQUEST_ID / "labs.csv").read_text() == "a\n1\n"
    assert METADATA_FILES <= {p.name for p in (tmp_path / REQUEST_ID).iterdir()}
