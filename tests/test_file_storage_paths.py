"""#468, ADR 0037: FileStorageService keeps every file inside its request's directory.

A name that isn't one safe path component is rejected: writes raise
ValueError, reads come back empty. Real filesystem under tmp_path.
"""

import os

import pandas as pd
import pytest

from app.services.file_storage import FileStorageService

REQ = "REQ-20261113-ABCD1234"

UNSAFE_NAMES = [
    "../escape.csv",
    "../../escape.csv",
    "..",
    ".",
    "",
    "sub/escape.csv",
    "..\\escape.csv",
    "bad\x00name.csv",
]


@pytest.fixture
def storage(tmp_path):
    return FileStorageService(base_path=str(tmp_path / "deliveries"))


def _outside_files(tmp_path):
    deliveries = tmp_path / "deliveries"
    return sorted(p for p in tmp_path.rglob("*") if p.is_file() and deliveries not in p.parents)


@pytest.mark.parametrize("filename", UNSAFE_NAMES + ["ABSOLUTE"])
def test_save_csv_rejects_a_filename_that_leaves_the_request_directory(storage, tmp_path, filename):
    if filename == "ABSOLUTE":
        filename = str(tmp_path / "absolute.csv")

    with pytest.raises(ValueError):
        storage.save_csv(REQ, filename, pd.DataFrame({"a": [1]}))

    assert _outside_files(tmp_path) == []


def test_get_file_path_returns_a_delivered_file(storage):
    storage.save_text_file(REQ, "Lab Results.csv", "a\n1\n")

    path = storage.get_file_path(REQ, "Lab Results.csv")

    assert path is not None and path.read_text() == "a\n1\n"


@pytest.fixture
def secret(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("outside the delivery root")
    return secret


@pytest.mark.parametrize("filename", UNSAFE_NAMES + ["ABSOLUTE"])
def test_get_file_path_refuses_names_outside_the_request_directory(storage, secret, filename):
    # The sibling request's file must not be reachable through `..`.
    storage.save_text_file("REQ-OTHER", "escape.csv", "another request's data")
    if filename == "ABSOLUTE":
        filename = str(secret)

    assert storage.get_file_path(REQ, filename) is None


def test_get_file_path_refuses_a_symlink_that_points_outside(storage, secret):
    request_dir = storage._get_request_directory(REQ)
    os.symlink(secret, request_dir / "link.csv")

    assert storage.get_file_path(REQ, "link.csv") is None


@pytest.mark.parametrize("request_id", ["..", "../REQ-OTHER", "REQ/../..", "ABSOLUTE"])
def test_a_request_id_outside_the_delivery_root_is_refused(storage, secret, request_id):
    if request_id == "ABSOLUTE":
        request_id = str(secret.parent)

    assert storage.get_file_path(request_id, "secret.txt") is None
    assert storage.list_files(request_id) == []
    assert storage.create_download_zip(request_id) is None
    assert storage.delete_request_data(request_id) is False
    assert secret.exists()


def test_a_request_id_symlinked_outside_the_delivery_root_is_refused(storage, secret):
    os.symlink(secret.parent, storage.base_path / "REQ-LINK")

    assert storage.get_file_path("REQ-LINK", "secret.txt") is None
    assert storage.list_files("REQ-LINK") == []


def test_download_zip_leaves_out_a_symlink_that_points_outside(storage, secret):
    import zipfile

    storage.save_text_file(REQ, "cohort.csv", "a\n1\n")
    os.symlink(secret, storage._get_request_directory(REQ) / "link.csv")

    zip_path = storage.create_download_zip(REQ)

    with zipfile.ZipFile(zip_path) as zf:
        assert zf.namelist() == ["cohort.csv"]
