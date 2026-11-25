import pytest

import paths


@pytest.mark.parametrize(
    "stored",
    [
        "uploads/a.jpg",
        "uploads\\a.jpg",
        "C:\\Users\\someone\\FindYU\\backend\\uploads\\a.jpg",
        "/abs/path/uploads/a.jpg",
        "a.jpg",
    ],
)
def test_filename_and_normalize(stored):
    assert paths.image_filename(stored) == "a.jpg"
    assert paths.normalize_stored_path(stored) == "uploads/a.jpg"


def test_empty_values():
    assert paths.image_filename(None) is None
    assert paths.image_filename("") is None
    assert paths.resolve_image_path(None) is None
    assert paths.normalize_stored_path(None) is None


def test_resolve_backslash_path_to_real_file(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "UPLOAD_DIR", tmp_path)
    (tmp_path / "x.jpg").write_bytes(b"fake")

    assert paths.resolve_image_path("uploads\\x.jpg") == tmp_path / "x.jpg"
    assert paths.resolve_image_path("uploads/x.jpg") == tmp_path / "x.jpg"
    assert paths.resolve_image_path("uploads\\missing.jpg") is None


def test_to_stored_path_is_posix():
    assert paths.to_stored_path("abc.png") == "uploads/abc.png"
