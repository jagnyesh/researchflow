"""#477, ADR 0038: extraction writes every data element's CSV or fails.

Rows are synthetic. The SQL layer is stubbed (`_execute_phenotype_query`,
`_extract_data_element`, `_extract_data_element_preview`); the agent's
`extract_data` and `extract_preview` tasks and `FileStorageService` run for
real against a temporary delivery directory.
"""

import logging
from pathlib import Path

import pytest

from app.agents.extraction_agent import FORM_DATA_ELEMENTS, DataExtractionAgent

REQUEST_ID = "REQ-477"
UNSAFE = "Blood pressure (systolic/diastolic)"


@pytest.fixture(autouse=True)
def delivery_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DELIVERY_PATH", str(tmp_path))
    return tmp_path


def _row(element: str) -> dict:
    return {"patient_id": "101", "value_string": f"synthetic {len(element)}"}


def _agent(monkeypatch, calls: list) -> DataExtractionAgent:
    agent = DataExtractionAgent()

    async def cohort(sql, params):
        calls.append("cohort")
        return [{"patient_id": "101"}]

    async def element(data_element, patient_ids, time_period, limit=None):
        calls.append(data_element)
        return [_row(data_element)]

    monkeypatch.setattr(agent, "_execute_phenotype_query", cohort)
    monkeypatch.setattr(agent, "_extract_data_element", element)
    monkeypatch.setattr(agent, "_extract_data_element_preview", element)
    return agent


def _context(elements: list) -> dict:
    return {
        "request_id": REQUEST_ID,
        "structured_requirements": {"phi_level": "identified", "data_elements": elements},
        "sql_query": "SELECT 1",
    }


def _written(delivery_dir: Path) -> set:
    request_dir = delivery_dir / REQUEST_ID
    return {p.name for p in request_dir.iterdir()} if request_dir.exists() else set()


@pytest.mark.asyncio
async def test_every_form_element_gets_a_csv_that_exists(monkeypatch, delivery_dir):
    agent = _agent(monkeypatch, [])

    result = await agent.execute_task("extract_data", _context(list(FORM_DATA_ELEMENTS)))

    formatted = result["data_package"]["formatted_data"]
    listed = [f["filename"] for f in formatted["files"]]
    assert len(listed) == len(set(listed)), listed
    assert set(listed) == _written(delivery_dir)
    assert {Path(p).name for p in formatted["file_paths"]} == set(listed)
    # One CSV per non-demographic form element, plus Demographics and the combined file.
    assert len(listed) == len(FORM_DATA_ELEMENTS) + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("task", ["extract_data", "extract_preview"])
async def test_an_unsafe_name_fails_before_anything_runs(monkeypatch, delivery_dir, caplog, task):
    calls = []
    agent = _agent(monkeypatch, calls)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ValueError) as raised:
        await agent.execute_task(task, _context(["Lab A", UNSAFE, "Lab B"]))

    assert calls == []
    assert _written(delivery_dir) == set()
    assert "position 2" in caplog.text
    for text in (str(raised.value), caplog.text):
        assert "systolic" not in text


@pytest.mark.asyncio
async def test_a_failed_write_fails_extraction_and_removes_what_it_wrote(monkeypatch, delivery_dir):
    agent = _agent(monkeypatch, [])
    # A directory where the last element's CSV goes makes that write fail
    # after the earlier CSVs are on disk.
    blocker = f"{FORM_DATA_ELEMENTS[-1]}.csv"
    (delivery_dir / REQUEST_ID / blocker).mkdir(parents=True)

    with pytest.raises(OSError):
        await agent.execute_task("extract_data", _context(list(FORM_DATA_ELEMENTS)))

    assert _written(delivery_dir) == {blocker}


class _Unwritable:
    def __str__(self):
        raise RuntimeError("synthetic write failure")


@pytest.mark.asyncio
async def test_a_write_that_fails_midway_leaves_no_partial_csv(monkeypatch, delivery_dir):
    agent = _agent(monkeypatch, [])

    async def element(data_element, patient_ids, time_period):
        row = _row(data_element)
        if data_element == FORM_DATA_ELEMENTS[-1]:
            return [row, {**row, "value_string": _Unwritable()}]
        return [row]

    monkeypatch.setattr(agent, "_extract_data_element", element)

    with pytest.raises(RuntimeError):
        await agent.execute_task("extract_data", _context(list(FORM_DATA_ELEMENTS)))

    assert _written(delivery_dir) == set()
