"""Fehlerbild-Sammlung (utils/failure_images.py): ablegen, aufräumen, wiederfinden."""

from __future__ import annotations

import os
import re
import time

import pytest

from backend.app.core.config import settings
from backend.app.utils import failure_images

NAME_RE = failure_images._FILENAME_RE


@pytest.fixture(autouse=True)
def isolated_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    return tmp_path / "failure_images"


def test_save_uses_a_unguessable_name_and_sanitizes_the_event(isolated_dir):
    name = failure_images.save_failure_image(b"\xff\xd8\xffjpeg", "Plate Not Empty!")
    assert name is not None and NAME_RE.fullmatch(name)
    # Wie bei den Benachrichtigungs-Fotos: fremde Zeichen wandern komplett raus.
    assert name.startswith("fail_platenotempty_")
    assert (isolated_dir / name).read_bytes() == b"\xff\xd8\xffjpeg"


def test_empty_image_is_not_saved(isolated_dir):
    assert failure_images.save_failure_image(b"", "x") is None
    assert not isolated_dir.exists() or list(isolated_dir.iterdir()) == []


def test_find_rejects_foreign_names_and_traversal(isolated_dir):
    good = failure_images.save_failure_image(b"x", "ai")
    assert failure_images.find_failure_image(good) is not None
    assert failure_images.find_failure_image(good[:-4] + "other.jpg") is None
    assert failure_images.find_failure_image("../" + good) is None
    assert failure_images.find_failure_image("\\\\" + good) is None
    assert failure_images.find_failure_image("random.jpg") is None


def test_list_is_newest_first_with_parsed_event(isolated_dir):
    first = failure_images.save_failure_image(b"a", "ai")
    time.sleep(0.02)
    second = failure_images.save_failure_image(b"b", "plate_not_empty")
    rows = failure_images.list_failure_images()
    assert [row["name"] for row in rows] == [second, first]
    assert rows[0]["event"] == "plate_not_empty"
    assert rows[0]["size"] == 1 and rows[1]["size"] == 1
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", rows[0]["timestamp"])


def test_pruning_removes_oldest_over_the_count_limit(isolated_dir, monkeypatch):
    names = [failure_images.save_failure_image(f"n{i}".encode(), "ai") for i in range(5)]
    base = time.time()
    for i, name in enumerate(names):
        os.utime(isolated_dir / name, (base - 500 + i, base - 500 + i))
    monkeypatch.setattr(failure_images, "_MAX_FILES", 3)
    failure_images._prune(isolated_dir)
    remaining = sorted(p.name for p in isolated_dir.iterdir())
    assert names[0] not in remaining and names[1] not in remaining
    assert len(remaining) == 3


def test_pruning_removes_expired_files(isolated_dir, monkeypatch):
    old = failure_images.save_failure_image(b"alt", "ai")
    fresh = failure_images.save_failure_image(b"neu", "ai")
    old_age = failure_images._MAX_AGE_SECONDS + 10
    os.utime(isolated_dir / old, (time.time() - old_age, time.time() - old_age))
    failure_images.save_failure_image(b"trigger", "ai")
    assert not (isolated_dir / old).exists()
    assert (isolated_dir / fresh).exists()


def test_pruning_counts_survivors_not_the_old_total(isolated_dir, monkeypatch):
    """Regression: zu alte Bilder dürfen die Übergrenze nicht auf die frische Menge anrechnen.

    Vorher wurden 600 Bilder mit 300 alten zu 300 statt 500 aufgeräumt — die Übergrenze wurde auf die
    alte Gesamtzahl gerechnet und traf danach frische Bilder.
    """
    old = [failure_images.save_failure_image(f"alt{i}".encode(), "ai") for i in range(5)]
    fresh = [failure_images.save_failure_image(f"neu{i}".encode(), "ai") for i in range(5)]
    age = failure_images._MAX_AGE_SECONDS + 60
    for i, name in enumerate(old):
        os.utime(isolated_dir / name, (time.time() - age - i, time.time() - age - i))
    monkeypatch.setattr(failure_images, "_MAX_FILES", 6)
    failure_images._prune(isolated_dir)
    remaining = {p.name for p in isolated_dir.iterdir()}
    assert remaining == set(fresh)
    assert len(remaining) == 5  # unter der Grenze: nichts Frisches wird gelöscht


def test_delete_only_touches_valid_entries(isolated_dir):
    name = failure_images.save_failure_image(b"x", "ai")
    assert failure_images.delete_failure_image(name) is True
    assert not (isolated_dir / name).exists()
    assert failure_images.delete_failure_image(name) is False
    assert failure_images.delete_failure_image("../x.jpg") is False


def test_broken_directory_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "base_dir", tmp_path)
    # Eine **Datei** am Platz des Bilderordners zwingt jedes mkdir in den OSError-Pfad.
    blocker = tmp_path / "failure_images"
    blocker.write_text("kein Ordner", encoding="utf-8")
    monkeypatch.setattr(failure_images, "failure_images_dir", lambda: blocker)
    assert failure_images.save_failure_image(b"x", "ai") is None
    assert failure_images.list_failure_images() == []
    assert failure_images.delete_failure_image("fail_ai_20260101_000000_" + "a" * 32 + ".jpg") is False
