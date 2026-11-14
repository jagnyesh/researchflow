"""#468, ADR 0037: download routes serve only files inside the request's delivery directory.

Real JWTs, real auth dependency, real (test) database, real files under tmp_path.
"""

import os
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import research
from app.database import ResearchRequest, get_db_session, init_db
from app.database.workflow_states import WorkflowState
from app.security.auth import create_access_token
from app.services.file_storage import FileStorageService

SECRET = "outside the delivery root"


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    await init_db()
    deliveries = tmp_path / "deliveries"
    monkeypatch.setenv("DATA_DELIVERY_PATH", str(deliveries))

    email = f"alice-{uuid.uuid4().hex[:6]}@example.org"
    request_id = f"REQ-TEST-{uuid.uuid4().hex[:8].upper()}"
    async with get_db_session() as session:
        session.add(
            ResearchRequest(
                id=request_id,
                researcher_name="Synthetic Researcher",
                researcher_email=email,
                initial_request="synthetic request text",
                current_state=WorkflowState.COMPLETE.value,
            )
        )

    storage = FileStorageService(str(deliveries))
    storage.save_text_file(request_id, "cohort.csv", "a\n1\n")
    (tmp_path / "secret.txt").write_text(SECRET)
    (deliveries / "secret.txt").write_text(SECRET)
    os.symlink(tmp_path / "secret.txt", storage._get_request_directory(request_id) / "link.csv")

    token = create_access_token({"sub": email, "user_id": "USR-r", "role": "researcher"})
    app = FastAPI()
    app.include_router(research.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, request_id, {"Authorization": f"Bearer {token}"}


async def test_a_delivered_file_downloads(setup):
    client, request_id, auth = setup

    response = await client.get(f"/research/{request_id}/download/cohort.csv", headers=auth)

    assert response.status_code == 200
    assert response.text == "a\n1\n"


@pytest.mark.parametrize(
    "filename",
    [
        "..%2Fsecret.txt",
        "..%2F..%2Fsecret.txt",
        "%2E%2E%2Fsecret.txt",
        "..%5Csecret.txt",
        "%2Fetc%2Fhosts",
        "..",
        "link.csv",
    ],
)
async def test_download_never_serves_a_file_outside_the_request_directory(setup, filename):
    client, request_id, auth = setup

    response = await client.get(f"/research/{request_id}/download/{filename}", headers=auth)

    # httpx collapses a literal ".." segment client-side, so that case reaches
    # the status route; what matters is that no file is served.
    assert "attachment" not in response.headers.get("content-disposition", "")
    assert SECRET not in response.text


async def test_the_package_zip_leaves_out_a_symlink(setup):
    import io
    import zipfile

    client, request_id, auth = setup

    response = await client.get(f"/research/{request_id}/download", headers=auth)

    assert response.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert names == ["cohort.csv"]
