"""Signaturprüfung der Updates: nur Tags mit einem auf dem Pi hinterlegten Schlüssel werden angenommen."""

import shutil
import subprocess

import pytest

from backend.app.services import update_signature as us

needs_tools = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("ssh-keygen") is None, reason="git oder ssh-keygen fehlt"
)


def run(repo, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=repo, check=True, capture_output=True
    )


def make_key(tmp_path, name):
    key = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(key)], check=True)
    return key, (tmp_path / f"{name}.pub").read_text().strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    run(path, "init", "-q")
    (path / "a.txt").write_text("1")
    run(path, "add", "-A")
    run(path, "commit", "-q", "-m", "eins")
    return path


def sign_tag(repo, key, tag):
    run(repo, "-c", "gpg.format=ssh", "-c", f"user.signingkey={key}", "tag", "-s", "-m", tag, tag)


def allowed(tmp_path, *pubkeys):
    path = tmp_path / "allowed"
    path.write_text("".join(f'printlab namespaces="git" {k}\n' for k in pubkeys))
    return path


class TestRefNames:
    @pytest.mark.parametrize("name", ["v1.6.2", "v1.0.0b3", "release/1.2", "1.2.3-rc1"])
    def test_normal_tags_pass(self, name):
        assert us.is_safe_ref_name(name)

    @pytest.mark.parametrize(
        "name",
        ["", "-x", "--upload-pack=evil", "a..b", "v1 .0", "v1;rm", "v1.lock", "v1/", ".hidden", "a" * 200, "v1\n2"],
    )
    def test_dangerous_names_are_refused(self, name):
        assert not us.is_safe_ref_name(name)


class TestPolicy:
    def test_off_without_a_signers_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv(us.ENV_SIGNERS, raising=False)
        assert us.policy(tmp_path) == {"enforced": False, "reason": None}

    def test_enforced_with_a_valid_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv(us.ENV_SIGNERS, raising=False)
        (tmp_path / us.SIGNERS_NAME).write_text('me namespaces="git" ssh-ed25519 AAAAC3Nza\n')
        assert us.policy(tmp_path) == {"enforced": True, "reason": None}

    def test_an_empty_or_garbage_file_still_enforces_but_can_never_verify(self, tmp_path, monkeypatch):
        monkeypatch.delenv(us.ENV_SIGNERS, raising=False)
        (tmp_path / us.SIGNERS_NAME).write_text("# nur ein Kommentar\nkein schluessel\n")
        result = us.policy(tmp_path)
        assert result["enforced"] is True and result["reason"]

    def test_environment_variable_points_to_another_file(self, tmp_path, monkeypatch):
        other = tmp_path / "woanders"
        other.write_text('x namespaces="git" ssh-ed25519 AAAAC3Nza\n')
        monkeypatch.setenv(us.ENV_SIGNERS, str(other))
        assert us.signers_file(tmp_path / "leer") == other


@needs_tools
class TestVerifyTag:
    @pytest.mark.asyncio
    async def test_tag_signed_with_an_allowed_key_is_accepted(self, tmp_path, repo):
        key, pub = make_key(tmp_path, "erlaubt")
        sign_tag(repo, key, "v1.0.0")
        ok, message = await us.verify_tag("git", repo, "v1.0.0", allowed(tmp_path, pub))
        assert ok, message

    @pytest.mark.asyncio
    async def test_tag_signed_with_a_stranger_key_is_refused(self, tmp_path, repo):
        _, pub = make_key(tmp_path, "erlaubt")
        stranger, _ = make_key(tmp_path, "fremd")
        sign_tag(repo, stranger, "v1.0.0")
        ok, message = await us.verify_tag("git", repo, "v1.0.0", allowed(tmp_path, pub))
        assert not ok and "nicht gültig signiert" in message

    @pytest.mark.asyncio
    async def test_unsigned_annotated_and_lightweight_tags_are_refused(self, tmp_path, repo):
        _, pub = make_key(tmp_path, "erlaubt")
        run(repo, "tag", "-a", "-m", "x", "v-annotated")
        run(repo, "tag", "v-light")
        for tag in ("v-annotated", "v-light"):
            ok, _ = await us.verify_tag("git", repo, tag, allowed(tmp_path, pub))
            assert not ok

    @pytest.mark.asyncio
    async def test_a_branch_with_the_tag_name_cannot_stand_in(self, tmp_path, repo):
        _, pub = make_key(tmp_path, "erlaubt")
        run(repo, "branch", "v9.9.9")
        ok, _ = await us.verify_tag("git", repo, "v9.9.9", allowed(tmp_path, pub))
        assert not ok

    @pytest.mark.asyncio
    async def test_a_tag_moved_after_signing_is_refused(self, tmp_path, repo):
        key, pub = make_key(tmp_path, "erlaubt")
        sign_tag(repo, key, "v1.0.0")
        (repo / "a.txt").write_text("2")
        run(repo, "commit", "-q", "-am", "zwei")
        # ein Angreifer legt einen neuen, unsignierten Tag gleichen Namens auf einen anderen Stand
        run(repo, "tag", "-f", "-a", "-m", "gefaelscht", "v1.0.0")
        ok, _ = await us.verify_tag("git", repo, "v1.0.0", allowed(tmp_path, pub))
        assert not ok

    @pytest.mark.asyncio
    async def test_refuses_without_a_usable_key_or_with_a_bad_name(self, tmp_path, repo):
        key, pub = make_key(tmp_path, "erlaubt")
        sign_tag(repo, key, "v1.0.0")
        empty = tmp_path / "leer"
        empty.write_text("# nichts\n")
        assert not (await us.verify_tag("git", repo, "v1.0.0", empty))[0]
        assert not (await us.verify_tag("git", repo, "--hard", allowed(tmp_path, pub)))[0]

    @pytest.mark.asyncio
    async def test_missing_ssh_keygen_fails_closed(self, tmp_path, repo, monkeypatch):
        _, pub = make_key(tmp_path, "erlaubt")
        monkeypatch.setattr(us.shutil, "which", lambda name: None)
        ok, message = await us.verify_tag("git", repo, "v1.0.0", allowed(tmp_path, pub))
        assert not ok and "ssh-keygen" in message
