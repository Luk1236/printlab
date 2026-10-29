"""Externe Sicherung (werkzeuge/sicherung_extern.py): Ziel prüfen, sichern, prüfen, alte löschen, melden."""

import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "werkzeuge" / "sicherung_extern.py"
if not SCRIPT.exists():
    pytest.skip("werkzeuge/ fehlt in dieser Umgebung", allow_module_level=True)
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("sicherung_extern", SCRIPT)
se = importlib.util.module_from_spec(spec)
spec.loader.exec_module(se)


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    con = sqlite3.connect(d / "printlab.db")
    con.execute("create table t (v text)")
    con.execute("insert into t values ('x')")
    con.commit()
    con.close()
    (d / "hardware.json").write_text('{"a": 1}')
    return d


@pytest.fixture(autouse=True)
def other_disk(monkeypatch):
    """Im Test liegt alles auf einem Datenträger; die Prüfung 'anderer Datenträger' wird gesondert getestet."""
    monkeypatch.setattr(se, "same_device", lambda a, b: False)


class TestRunBackup:
    def test_creates_a_verified_copy(self, data, tmp_path):
        target = tmp_path / "usb"
        target.mkdir()
        result = se.run_backup(data, target)
        folder = Path(result["folder"])
        assert folder.parent == target and sorted(result["saved"]) == ["hardware.json", "printlab.db"]
        con = sqlite3.connect(folder / "printlab.db")
        assert con.execute("select v from t").fetchone()[0] == "x"
        con.close()

    def test_a_missing_target_is_never_created(self, data, tmp_path):
        target = tmp_path / "nicht-eingehaengt"
        with pytest.raises(RuntimeError, match="nicht erreichbar"):
            se.run_backup(data, target)
        assert not target.exists()  # nichts landet auf der SD-Karte

    def test_target_on_the_same_disk_is_refused_unless_allowed(self, data, tmp_path, monkeypatch):
        monkeypatch.setattr(se, "same_device", lambda a, b: True)
        target = tmp_path / "usb"
        target.mkdir()
        with pytest.raises(RuntimeError, match="demselben Datenträger"):
            se.run_backup(data, target)
        assert se.run_backup(data, target, allow_same_disk=True)["folder"]

    def test_a_corrupt_backup_is_deleted_and_reported(self, data, tmp_path, monkeypatch):
        target = tmp_path / "usb"
        target.mkdir()
        monkeypatch.setattr(se.backup_pruefen, "check_folder", lambda folder: ["printlab.db: kaputt"])
        with pytest.raises(RuntimeError, match="beschädigt"):
            se.run_backup(data, target)
        assert list(target.iterdir()) == []

    def test_a_failing_copy_leaves_nothing_behind(self, data, tmp_path, monkeypatch):
        target = tmp_path / "usb"
        target.mkdir()

        def boom(*a, **k):
            raise sqlite3.DatabaseError("Platte voll")

        monkeypatch.setattr(se.update_guard, "backup_data", boom)
        with pytest.raises(RuntimeError, match="fehlgeschlagen"):
            se.run_backup(data, target)
        assert list(target.iterdir()) == []

    def test_only_the_newest_backups_are_kept(self, data, tmp_path, monkeypatch):
        target = tmp_path / "usb"
        target.mkdir()
        stamps = iter(f"20260101-00000{i}" for i in range(6))
        monkeypatch.setattr(se.time, "strftime", lambda fmt: next(stamps))
        for _ in range(5):
            result = se.run_backup(data, target, keep=3)
        names = sorted(p.name for p in target.iterdir())
        assert len(names) == 3 and names[-1] == Path(result["folder"]).name

    def test_foreign_folders_are_never_deleted(self, data, tmp_path):
        target = tmp_path / "usb"
        (target / "meine-fotos").mkdir(parents=True)
        for _ in range(3):
            se.prune(target, 1)
        assert (target / "meine-fotos").exists()


class TestSecretsCopy:
    """Zugangsdatei nur bei ausdrücklichem Opt-in in der Sicherung (#sprint-2910)."""

    @pytest.fixture(autouse=True)
    def fake_home(self, tmp_path, monkeypatch):
        """copy_secrets liest Path.home()/.config/printlab.env — im Test ein erfundetes Home-Verzeichnis."""
        home = tmp_path / "home"
        monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
        self.home = home

    def _secrets(self, content: str = "PRINTLAB_GITHUB_TOKEN=geheim") -> Path:
        source = self.home / ".config" / "printlab.env"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(content, encoding="utf-8")
        return source

    def test_off_by_default(self, data, tmp_path):
        target = tmp_path / "usb"
        target.mkdir()
        self._secrets()
        folder = Path(se.run_backup(data, target)["folder"])
        assert [p.name for p in folder.iterdir() if p.suffix == ".env"] == []

    def test_opt_in_copies_the_access_file_privately(self, data, tmp_path):
        self._secrets()
        target = tmp_path / "usb"
        target.mkdir()
        result = se.run_backup(data, target, include_secrets=True)
        folder = Path(result["folder"])
        copy = folder / "printlab.env"
        assert copy.read_text(encoding="utf-8") == "PRINTLAB_GITHUB_TOKEN=geheim"
        assert result["secrets"] == "printlab.env (0600)"
        if os.name != "nt":
            assert copy.stat().st_mode & 0o077 == 0

    def test_missing_access_file_reports_none(self, data, tmp_path):
        target = tmp_path / "usb"
        target.mkdir()
        result = se.run_backup(data, target, include_secrets=True)
        assert result["secrets"] is None
        assert [p.name for p in Path(result["folder"]).iterdir() if p.suffix == ".env"] == []

    def test_main_wires_the_opt_in(self, data, tmp_path, monkeypatch):
        target = tmp_path / "usb"
        target.mkdir()
        monkeypatch.setattr(se, "DATA_DIR", data)
        monkeypatch.setenv("PRINTLAB_BACKUP_TARGET", str(target))
        captured = {}

        def fake_run_backup(data_dir, target_, keep, allow_same_disk, include_secrets=False):
            captured["include"] = include_secrets
            return {"folder": str(target_ / "x"), "saved": [], "removed": []}

        monkeypatch.setattr(se, "run_backup", fake_run_backup)
        monkeypatch.delenv("PRINTLAB_BACKUP_INCLUDE_SECRETS", raising=False)
        se.main()
        assert captured["include"] is False
        monkeypatch.setenv("PRINTLAB_BACKUP_INCLUDE_SECRETS", "1")
        se.main()
        assert captured["include"] is True


class TestMain:
    def test_nothing_configured_is_not_an_error(self, monkeypatch, capsys):
        monkeypatch.delenv("PRINTLAB_BACKUP_TARGET", raising=False)
        assert se.main() == 0
        assert "nichts zu tun" in capsys.readouterr().out

    def test_failure_is_reported_and_recorded(self, data, tmp_path, monkeypatch):
        sent = []
        monkeypatch.setattr(se, "DATA_DIR", data)
        monkeypatch.setenv("PRINTLAB_BACKUP_TARGET", str(tmp_path / "weg"))
        monkeypatch.setattr(se.ueberwachung, "make_notifier", lambda **kw: sent.append)
        assert se.main() == 1
        assert sent and "fehlgeschlagen" in sent[0]
        status = json.loads((data / "last_external_backup.json").read_text())
        assert status["ok"] is False

    def test_success_is_recorded_and_silent(self, data, tmp_path, monkeypatch):
        sent = []
        target = tmp_path / "usb"
        target.mkdir()
        monkeypatch.setattr(se, "DATA_DIR", data)
        monkeypatch.setenv("PRINTLAB_BACKUP_TARGET", str(target))
        monkeypatch.setattr(se.ueberwachung, "make_notifier", lambda **kw: sent.append)
        assert se.main() == 0
        assert not sent
        assert json.loads((data / "last_external_backup.json").read_text())["ok"] is True

    def test_bad_keep_value_falls_back_to_the_default(self, data, tmp_path, monkeypatch):
        target = tmp_path / "usb"
        target.mkdir()
        monkeypatch.setattr(se, "DATA_DIR", data)
        monkeypatch.setenv("PRINTLAB_BACKUP_TARGET", str(target))
        monkeypatch.setenv("PRINTLAB_BACKUP_KEEP", "viele")
        monkeypatch.setattr(se.ueberwachung, "make_notifier", lambda **kw: print)
        assert se.main() == 0

    @pytest.mark.skipif(os.name == "nt", reason="Dateirechte nur unter POSIX")
    def test_backup_files_are_private(self, data, tmp_path):
        target = tmp_path / "usb"
        target.mkdir()
        folder = Path(se.run_backup(data, target)["folder"])
        assert (folder / "printlab.db").stat().st_mode & 0o077 == 0
