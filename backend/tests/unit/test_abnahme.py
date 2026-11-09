"""Tests für das Abnahme-Werkzeug (werkzeuge/abnahme.py, Stufen 3 & 4)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "werkzeuge" / "abnahme.py"
if not SCRIPT.exists():
    pytest.skip("werkzeuge/ fehlt in dieser Umgebung", allow_module_level=True)

spec = importlib.util.spec_from_file_location("abnahme", SCRIPT)
abnahme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(abnahme)


def test_einvoice_schema_check_is_ok():
    level, title, detail = abnahme.check_einvoice_schema()
    assert level == abnahme.OK
    assert "XRechnung 3.0" in title
    assert "BT-146" in detail


def test_gpio_config_check_is_ok():
    level, title, detail = abnahme.check_gpio_config()
    assert level == abnahme.OK
    assert "GPIO-Mechanik" in title
    assert "konfliktfrei" in detail


def test_repo_hygiene_check_is_ok():
    level, title, _detail = abnahme.check_repo_hygiene()
    assert level == abnahme.OK
    assert title == "Repo-Hygiene"


def test_durchstich_runs_stage_3_and_4_workflows_cleanly(monkeypatch):
    """Der Durchstich slict im Betrieb mit dem echten OrcaSlicer. Im Test wird der nicht aus dem Netz geladen und
    nicht gestartet: Ein Unit-Test darf weder GitHub brauchen noch an fehlenden Systembibliotheken (libOpenGL im
    Docker-Image) scheitern. Die Slicer-Aufrufe selbst sind in test_builtin_slicer.py abgedeckt."""
    from backend.app.services import builtin_slicer
    from backend.app.services.slicer_cli import SliceOutput

    monkeypatch.setattr(
        builtin_slicer, "slice_model_builtin", lambda *args, **kwargs: SliceOutput(b"PK stub", 600, 1.5)
    )
    steps = abnahme.run_durchstich()
    assert len(steps) == 5
    for step in steps:
        assert step["level"] == abnahme.OK, f"{step['title']} fehlgeschlagen: {step['detail']}"


def test_prepare_signature_writes_allowed_signers(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    ssh_dir = fake_home / ".ssh"
    ssh_dir.mkdir(parents=True)
    monkeypatch.setattr(abnahme, "HOME", fake_home)

    # Ohne Schlüssel -> WARN mit ssh-keygen-Befehl
    level, msg = abnahme.prepare_signature(root=tmp_path, data_dir=tmp_path / "data")
    assert level == abnahme.WARN
    assert "ssh-keygen" in msg

    # Mit Schlüssel -> OK und update_allowed_signers geschrieben
    pubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestKey printlab-releases"
    (ssh_dir / "printlab_signing.pub").write_text(pubkey + "\n", encoding="utf-8")
    level, msg = abnahme.prepare_signature(root=tmp_path, data_dir=tmp_path / "data")
    assert level == abnahme.OK
    signers = (tmp_path / "data" / "update_allowed_signers").read_text(encoding="utf-8")
    assert 'printlab namespaces="git" ssh-ed25519' in signers
