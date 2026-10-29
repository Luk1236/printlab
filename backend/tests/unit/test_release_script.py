"""Release-Skript: Prüfung vor dem Tag, Tag-Nachricht aus dem Changelog."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "werkzeuge" / "release.py"

pytestmark = pytest.mark.skipif(
    not SCRIPT.is_file() or not (ROOT / ".git").exists(),
    reason="Release-Skript und Git-Repository sind im Test-Container nicht vorhanden",
)


def _load():
    sys.path.insert(0, str(ROOT / "werkzeuge"))
    try:
        spec = importlib.util.spec_from_file_location("printlab_release", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_release_title_comes_from_the_changelog():
    module = _load()
    assert module.release_title("v1.13.0") == "Fehlerhilfe"
    assert module.release_title("v1.12.0") == "Geschäft, Warteschlange und Assistent"


def test_a_mismatched_tag_is_refused_before_anything_is_created(capsys):
    module = _load()
    assert module.main(["--check-only", "v999.0.0"]) == 1
    output = capsys.readouterr().err
    assert "MANGEL" in output
    tags = subprocess.run(
        ["git", "tag", "--list", "v999.0.0"],  # noqa: S607 - fixed arguments
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert tags == ""


def test_a_dirty_tree_blocks_the_release(monkeypatch, tmp_path):
    module = _load()
    monkeypatch.setattr(module.gate, "check", lambda tag, root: [])
    monkeypatch.setattr(module, "_git", lambda *args: " M frontend/src/App.tsx\n")
    assert module.main(["v1.13.0"]) == 1


@pytest.mark.parametrize("tag", ["1.13.0", "v1.13", "release-1"])
def test_requires_a_semver_tag(tag):
    module = _load()
    assert module.main(["--check-only", tag]) == 1
