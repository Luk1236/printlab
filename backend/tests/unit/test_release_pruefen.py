"""Release-Prüfung (werkzeuge/release_pruefen.py): Version, Changelog und Oberfläche passen zum Tag."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "werkzeuge" / "release_pruefen.py"
if not SCRIPT.exists():
    pytest.skip("werkzeuge/ fehlt in dieser Umgebung", allow_module_level=True)
spec = importlib.util.spec_from_file_location("release_pruefen", SCRIPT)
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git fehlt in dieser Umgebung")

CHANGELOG = """# Changelog

## v1.2.0 (01.01.2027) — Neu

- Etwas Neues.

## v1.1.0 (01.12.2026)

- Etwas Altes.
"""


def git(root, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True
    )


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "r"
    (root / "backend" / "app" / "core").mkdir(parents=True)
    (root / "frontend" / "src" / "__tests__").mkdir(parents=True)
    (root / "static").mkdir()
    (root / "backend" / "app" / "core" / "config.py").write_text('PRINTLAB_VERSION = "1.2.0"\n')
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (root / "frontend" / "src" / "app.tsx").write_text("export const a = 1;\n")
    (root / "frontend" / "src" / "__tests__" / "a.test.tsx").write_text("test\n")
    (root / "frontend" / "package.json").write_text("{}\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "x")
    return root


def commit_all(root):
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "y")


class TestStaticHash:
    def test_same_sources_same_hash(self, repo):
        assert rp.static_source_hash(repo) == rp.static_source_hash(repo)

    def test_changing_a_source_file_changes_the_hash(self, repo):
        before = rp.static_source_hash(repo)
        (repo / "frontend" / "src" / "app.tsx").write_text("export const a = 2;\n")
        commit_all(repo)
        assert rp.static_source_hash(repo) != before

    def test_tests_do_not_count(self, repo):
        before = rp.static_source_hash(repo)
        (repo / "frontend" / "src" / "__tests__" / "a.test.tsx").write_text("anders\n")
        commit_all(repo)
        assert rp.static_source_hash(repo) == before

    def test_line_endings_do_not_matter(self, repo):
        before = rp.static_source_hash(repo)
        git(repo, "config", "core.autocrlf", "true")
        (repo / "frontend" / "src" / "app.tsx").write_bytes(b"export const a = 1;\r\n")
        git(repo, "add", "-A")  # nach dem Normalisieren der Zeilenenden gibt es nichts mehr zu committen
        assert rp.static_source_hash(repo) == before


class TestCheck:
    def stamp(self, repo):
        rp.write_static_hash(repo)
        commit_all(repo)

    def test_everything_matches(self, repo):
        self.stamp(repo)
        assert rp.check("v1.2.0", repo) == []

    def test_wrong_version(self, repo):
        self.stamp(repo)
        assert any("PRINTLAB_VERSION" in p for p in rp.check("v1.3.0", repo))

    def test_missing_changelog_section(self, repo):
        (repo / "backend" / "app" / "core" / "config.py").write_text('PRINTLAB_VERSION = "1.4.0"\n')
        self.stamp(repo)
        assert any("CHANGELOG" in p for p in rp.check("v1.4.0", repo))

    def test_missing_or_stale_build(self, repo):
        assert any("fehlt" in p for p in rp.check("v1.2.0", repo))
        self.stamp(repo)
        (repo / "frontend" / "src" / "app.tsx").write_text("export const a = 9;\n")
        commit_all(repo)
        assert any("nicht aktuell" in p for p in rp.check("v1.2.0", repo))

    @pytest.mark.parametrize("tag", ["1.2.0", "v1.2", "vx", "v1.2.0; rm", ""])
    def test_bad_tag_names(self, repo, tag):
        assert len(rp.check(tag, repo)) == 1

    def test_beta_tags_are_accepted_in_form(self, repo):
        assert not any("Form" in p for p in rp.check("v1.2.0b1", repo))


class TestNotes:
    def test_section_for_a_version(self, repo):
        text = rp.changelog_section(repo, "1.2.0")
        assert text.startswith("## v1.2.0") and "Etwas Neues" in text and "Etwas Altes" not in text

    def test_unknown_version(self, repo):
        assert rp.changelog_section(repo, "9.9.9") is None

    def test_crlf_changelog(self, repo):
        (repo / "CHANGELOG.md").write_bytes(CHANGELOG.replace("\n", "\r\n").encode())
        assert "Etwas Neues" in rp.changelog_section(repo, "1.2.0")


def test_the_real_repository_has_a_matching_version_and_changelog():
    root = Path(__file__).resolve().parents[3]
    if not (root / "CHANGELOG.md").is_file():
        pytest.skip("Quellordner fehlt in dieser Umgebung")
    version = rp.current_version(root)
    assert version and rp.changelog_section(root, version), (
        "CHANGELOG.md braucht einen Abschnitt für die aktuelle Version"
    )
