"""Das Einrichtungs-Skript für den lokalen KI-Assistenten und seine Voreinstellungen."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.services import assistant_config

SKRIPT = Path(__file__).resolve().parents[3] / "werkzeuge" / "ki_einrichten.sh"

if not SKRIPT.is_file():  # das Test-Image enthält werkzeuge/ nicht
    pytest.skip("werkzeuge/ki_einrichten.sh fehlt in dieser Umgebung", allow_module_level=True)

TEXT = SKRIPT.read_text(encoding="utf-8")


def test_the_default_model_matches_the_programs_default():
    model = re.search(r'^MODEL="([^"]+)"', TEXT, re.M)
    assert model and model.group(1) == assistant_config.DEFAULTS["model"]
    assert re.search(r'^URL="([^"]+)"', TEXT, re.M).group(1) == assistant_config.DEFAULTS["base_url"]


def test_the_script_is_strict_and_never_uses_sudo_on_its_own():
    assert TEXT.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in TEXT
    code = [line for line in TEXT.splitlines() if not line.lstrip().startswith("#")]
    assert not any(re.search(r"(^|[;&|]\s*)sudo\s", line) for line in code if "echo" not in line)
    assert "\r" not in TEXT  # Windows-Zeilenenden würden das Skript auf dem Pi unbrauchbar machen


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash fehlt")
def test_the_syntax_is_valid():
    result = subprocess.run(["bash", "-n", str(SKRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash fehlt")
def test_an_unknown_option_is_refused():
    result = subprocess.run(["bash", str(SKRIPT), "--gibtsnicht"], capture_output=True, text=True, check=False)
    assert result.returncode == 2 and "Unbekannte Option" in result.stderr
