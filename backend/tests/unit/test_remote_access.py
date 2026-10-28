"""Remote access via Tailscale in userspace mode: parsing, checksum, extraction and command lines (no real tailscale)."""

import hashlib
import io
import json
import tarfile

import httpx
import pytest

from backend.app.services import remote_access as ra


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ra, "STATE_DIR", tmp_path / "ts")
    monkeypatch.setattr(ra, "BIN_DIR", tmp_path / "ts" / "bin")
    monkeypatch.setattr(ra, "SOCKET", tmp_path / "ts" / "tailscaled.sock")
    monkeypatch.setattr(ra, "STATE_FILE", tmp_path / "ts" / "tailscaled.state")
    monkeypatch.setattr(ra, "CONFIG_PATH", tmp_path / "ts" / "remote_access.json")
    monkeypatch.setattr(ra, "_daemon", None)
    monkeypatch.setattr(ra, "supported", lambda: True)
    monkeypatch.setattr(ra, "_system_cli", lambda: None)


def make_tar(names=("tailscale_1.80.2_arm64/tailscale", "tailscale_1.80.2_arm64/tailscaled")):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in names:
            data = b"#!/bin/sh\n"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def fake_server(monkeypatch, tarball, *, checksum=None, listing_name="tailscale_1.80.2_arm64.tgz"):
    digest = checksum or hashlib.sha256(tarball).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("?mode=json"):
            return httpx.Response(200, json={"Tarballs": {"arm64": listing_name, "amd64": listing_name}})
        if url.endswith(".sha256"):
            return httpx.Response(200, text=f"{digest}  {listing_name}\n")
        return httpx.Response(200, content=tarball)

    real = httpx.AsyncClient
    monkeypatch.setattr(ra.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(ra.platform, "machine", lambda: "aarch64")


class TestInstall:
    @pytest.mark.asyncio
    async def test_downloads_verifies_and_extracts(self, monkeypatch):
        fake_server(monkeypatch, make_tar())
        assert await ra.install() == "1.80.2"
        for name in ("tailscale", "tailscaled"):
            assert (ra.BIN_DIR / name).is_file()

    @pytest.mark.asyncio
    async def test_wrong_checksum_is_refused_and_nothing_is_written(self, monkeypatch):
        fake_server(monkeypatch, make_tar(), checksum="0" * 64)
        with pytest.raises(ra.RemoteAccessError, match="Prüfsumme"):
            await ra.install()
        assert not ra.BIN_DIR.exists() or not list(ra.BIN_DIR.iterdir())

    @pytest.mark.asyncio
    async def test_suspicious_package_name_is_refused(self, monkeypatch):
        fake_server(monkeypatch, make_tar(), listing_name="../../etc/evil.tgz")
        with pytest.raises(ra.RemoteAccessError, match="passendes"):
            await ra.install()

    @pytest.mark.asyncio
    async def test_unknown_architecture(self, monkeypatch):
        fake_server(monkeypatch, make_tar())
        monkeypatch.setattr(ra.platform, "machine", lambda: "riscv64")
        with pytest.raises(ra.RemoteAccessError, match="rchitektur"):
            await ra.install()

    @pytest.mark.asyncio
    async def test_not_on_windows(self, monkeypatch):
        monkeypatch.setattr(ra, "supported", lambda: False)
        with pytest.raises(ra.RemoteAccessError, match="Linux"):
            await ra.install()

    def test_archive_without_the_daemon_is_refused(self):
        with pytest.raises(ra.RemoteAccessError, match="erwarteten"):
            ra._extract(make_tar(("t/tailscale",)))

    def test_only_the_two_programs_are_extracted_and_never_outside_bin(self, tmp_path):
        ra._extract(make_tar(("t/tailscale", "t/tailscaled", "t/evil.sh", "../../outside/tailscale")))
        assert sorted(p.name for p in ra.BIN_DIR.iterdir()) == ["tailscale", "tailscaled"]
        assert not (tmp_path / "outside").exists()


class TestStatus:
    @pytest.mark.asyncio
    async def test_not_installed(self):
        info = await ra.status()
        assert info["installed"] is False and info["state"] == "off"

    @pytest.mark.asyncio
    async def test_unsupported_platform(self, monkeypatch):
        monkeypatch.setattr(ra, "supported", lambda: False)
        assert (await ra.status())["supported"] is False

    @pytest.mark.asyncio
    async def test_connected_with_share(self, monkeypatch):
        ra._extract(make_tar())
        monkeypatch.setattr(ra, "_daemon_running", lambda: True)

        async def fake_ts(*args, timeout=30.0):
            if args[0] == "status":
                data = {
                    "BackendState": "Running",
                    "Self": {"TailscaleIPs": ["100.64.0.7"], "DNSName": "printlab.tail1234.ts.net."},
                }
                return 0, json.dumps(data)
            return 0, "|-- tcp://100.64.0.7:8000 (TCP forwarder)\n|--> tcp://localhost:8000\n"

        monkeypatch.setattr(ra, "_ts", fake_ts)
        info = await ra.status()
        assert info["state"] == "connected" and info["ips"] == ["100.64.0.7"]
        assert info["dns_name"] == "printlab.tail1234.ts.net" and info["serving"] is True

    @pytest.mark.asyncio
    async def test_needs_login_reports_the_link(self, monkeypatch):
        ra._extract(make_tar())
        monkeypatch.setattr(ra, "_daemon_running", lambda: True)

        async def fake_ts(*args, timeout=30.0):
            return 1, json.dumps({"BackendState": "NeedsLogin", "AuthURL": "https://login.tailscale.com/a/abc123"})

        monkeypatch.setattr(ra, "_ts", fake_ts)
        info = await ra.status()
        assert info["state"] == "login" and info["login_url"].endswith("/a/abc123")

    @pytest.mark.asyncio
    async def test_installed_but_daemon_not_running(self):
        ra._extract(make_tar())
        assert (await ra.status())["state"] == "stopped"

    @pytest.mark.asyncio
    async def test_garbage_output_does_not_raise(self, monkeypatch):
        ra._extract(make_tar())
        monkeypatch.setattr(ra, "_daemon_running", lambda: True)

        async def fake_ts(*args, timeout=30.0):
            return 0, "kein json"

        monkeypatch.setattr(ra, "_ts", fake_ts)
        assert (await ra.status())["error"]


class TestCommands:
    @pytest.mark.asyncio
    async def test_login_extracts_the_link(self, monkeypatch):
        async def fake_ts(*args, timeout=30.0):
            assert args[0] == "up" and "--accept-dns=false" in args
            return 1, "\nTo authenticate, visit:\n\n\thttps://login.tailscale.com/a/XyZ9876\n"

        monkeypatch.setattr(ra, "_ts", fake_ts)
        assert await ra.login() == "https://login.tailscale.com/a/XyZ9876"

    @pytest.mark.asyncio
    async def test_login_when_already_connected_returns_none(self, monkeypatch):
        async def fake_ts(*args, timeout=30.0):
            return 0, "Success."

        async def fake_status():
            return {"state": "connected", "login_url": None}

        monkeypatch.setattr(ra, "_ts", fake_ts)
        monkeypatch.setattr(ra, "status", fake_status)
        assert await ra.login() is None

    @pytest.mark.asyncio
    async def test_share_uses_a_tcp_forward_only_inside_the_tailnet(self, monkeypatch):
        seen = []

        async def fake_ts(*args, timeout=30.0):
            seen.append(args)
            return 0, ""

        monkeypatch.setattr(ra, "_ts", fake_ts)
        await ra.share(8000)
        assert seen == [("serve", "--bg", "--tcp=8000", "tcp://localhost:8000")]
        assert json.loads(ra.CONFIG_PATH.read_text())["enabled"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("port", [0, 70000, -1])
    async def test_share_rejects_bad_ports(self, port):
        with pytest.raises(ra.RemoteAccessError, match="Port"):
            await ra.share(port)

    @pytest.mark.asyncio
    async def test_share_failure_is_reported(self, monkeypatch):
        async def fake_ts(*args, timeout=30.0):
            return 2, "serve: HTTPS not enabled"

        monkeypatch.setattr(ra, "_ts", fake_ts)
        with pytest.raises(ra.RemoteAccessError, match="HTTPS not enabled"):
            await ra.share(8000)

    @pytest.mark.asyncio
    async def test_setup_installs_starts_logs_in_and_shares_when_connected(self, monkeypatch):
        order = []

        async def fake_install():
            order.append("install")
            ra._extract(make_tar())

        async def fake_start():
            order.append("start")

        async def fake_login():
            order.append("login")

        async def fake_status():
            return {"state": "connected", "login_url": None}

        async def fake_share(port):
            order.append(f"share:{port}")

        monkeypatch.setattr(ra, "install", fake_install)
        monkeypatch.setattr(ra, "start_daemon", fake_start)
        monkeypatch.setattr(ra, "login", fake_login)
        monkeypatch.setattr(ra, "status", fake_status)
        monkeypatch.setattr(ra, "share", fake_share)
        await ra.setup(8000)
        assert order == ["install", "start", "login", "share:8000"]

    @pytest.mark.asyncio
    async def test_setup_only_shares_after_the_login_succeeded(self, monkeypatch):
        order = []

        async def fake_install():
            ra._extract(make_tar())

        async def fake_start():
            return None

        async def fake_login():
            return "https://login.tailscale.com/a/abc"

        async def fake_status():
            return {"state": "login", "login_url": None}

        async def fake_share(port):
            order.append("share")

        monkeypatch.setattr(ra, "install", fake_install)
        monkeypatch.setattr(ra, "start_daemon", fake_start)
        monkeypatch.setattr(ra, "login", fake_login)
        monkeypatch.setattr(ra, "status", fake_status)
        monkeypatch.setattr(ra, "share", fake_share)
        result = await ra.setup(8000)
        assert order == [] and result["login_url"].endswith("/a/abc")

    @pytest.mark.asyncio
    async def test_disable_resets_and_turns_the_flag_off(self, monkeypatch):
        seen = []

        async def fake_ts(*args, timeout=30.0):
            seen.append(args[0])
            return 0, ""

        async def fake_status():
            return {"state": "off"}

        monkeypatch.setattr(ra, "_ts", fake_ts)
        monkeypatch.setattr(ra, "status", fake_status)
        ra._write_config({"enabled": True})
        await ra.disable()
        assert seen == ["serve", "down"]
        assert json.loads(ra.CONFIG_PATH.read_text())["enabled"] is False

    @pytest.mark.asyncio
    async def test_autostart_does_nothing_when_it_was_off(self, monkeypatch):
        called = []

        async def fake_start():
            called.append(1)

        monkeypatch.setattr(ra, "start_daemon", fake_start)
        await ra.autostart()
        assert called == []


class TestSlicerAccess:
    @pytest.mark.asyncio
    async def test_all_virtual_printer_ports_are_shared_inside_the_tailnet_only(self, monkeypatch):
        seen = []

        async def fake_ts(*args, timeout=30.0):
            seen.append(args)
            return 0, ""

        monkeypatch.setattr(ra, "_ts", fake_ts)
        await ra.share_slicer()
        assert len(seen) == len(ra.SLICER_PORTS)
        assert ("serve", "--bg", "--tcp=990", "tcp://localhost:990") in seen
        assert ("serve", "--bg", "--tcp=8883", "tcp://localhost:8883") in seen
        assert all("funnel" not in arg for call in seen for arg in call)  # nie ins öffentliche Internet
        assert json.loads(ra.CONFIG_PATH.read_text())["slicer"] is True

    def test_ports_cover_discovery_upload_control_and_passive_data(self):
        assert {3000, 3002, 990, 8883} <= set(ra.SLICER_PORTS)
        assert {50000, 50029} <= set(ra.SLICER_PORTS)
        assert 8000 not in ra.SLICER_PORTS

    @pytest.mark.asyncio
    async def test_a_failing_port_is_reported_with_its_number(self, monkeypatch):
        async def fake_ts(*args, timeout=30.0):
            return (2, "kaputt") if "--tcp=990" in args else (0, "")

        monkeypatch.setattr(ra, "_ts", fake_ts)
        with pytest.raises(ra.RemoteAccessError, match="Port 990"):
            await ra.share_slicer()

    @pytest.mark.asyncio
    async def test_unshare_turns_the_ports_off_and_keeps_the_web_share(self, monkeypatch):
        seen = []

        async def fake_ts(*args, timeout=30.0):
            seen.append(args)
            return 0, ""

        monkeypatch.setattr(ra, "_ts", fake_ts)
        ra._write_config({"enabled": True, "port": 8000, "slicer": True})
        await ra.unshare_slicer()
        assert ("serve", "--tcp=990", "off") in seen
        assert all("--tcp=8000" not in call for call in seen)
        config = json.loads(ra.CONFIG_PATH.read_text())
        assert config["slicer"] is False and config["enabled"] is True

    @pytest.mark.asyncio
    async def test_disable_also_clears_the_slicer_flag(self, monkeypatch):
        async def fake_ts(*args, timeout=30.0):
            return 0, ""

        monkeypatch.setattr(ra, "_ts", fake_ts)
        ra._write_config({"enabled": True, "slicer": True})
        await ra.disable()
        assert json.loads(ra.CONFIG_PATH.read_text())["slicer"] is False

    @pytest.mark.asyncio
    async def test_status_reports_the_slicer_flag(self):
        ra._write_config({"slicer": True})
        assert (await ra.status())["slicer"] is True


class TestHttps:
    @pytest.mark.asyncio
    async def test_https_is_served_by_tailscale_to_the_local_port_only(self, monkeypatch):
        seen = []

        async def fake_ts(*args, timeout=30.0):
            seen.append(args)
            return 0, ""

        monkeypatch.setattr(ra, "_ts", fake_ts)
        await ra.share_https(8000)
        assert seen == [("serve", "--bg", "--https=443", "http://127.0.0.1:8000")]
        assert all("funnel" not in arg for call in seen for arg in call)  # nie ins öffentliche Internet
        assert json.loads(ra.CONFIG_PATH.read_text())["https"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("port", [0, 70000])
    async def test_bad_ports_are_refused(self, port):
        with pytest.raises(ra.RemoteAccessError, match="Port"):
            await ra.share_https(port)

    @pytest.mark.asyncio
    async def test_tailscale_message_is_passed_on_when_https_is_not_enabled(self, monkeypatch):
        async def fake_ts(*args, timeout=30.0):
            return 1, "HTTPS is not enabled on your tailnet"

        monkeypatch.setattr(ra, "_ts", fake_ts)
        with pytest.raises(ra.RemoteAccessError, match="HTTPS is not enabled"):
            await ra.share_https(8000)

    @pytest.mark.asyncio
    async def test_unshare_turns_it_off_and_keeps_the_rest(self, monkeypatch):
        seen = []

        async def fake_ts(*args, timeout=30.0):
            seen.append(args)
            return 0, ""

        monkeypatch.setattr(ra, "_ts", fake_ts)
        ra._write_config({"enabled": True, "https": True, "slicer": True})
        await ra.unshare_https()
        assert seen == [("serve", "--https=443", "off")]
        config = json.loads(ra.CONFIG_PATH.read_text())
        assert config["https"] is False and config["enabled"] is True and config["slicer"] is True

    @pytest.mark.asyncio
    async def test_disable_clears_https_and_status_reports_the_address(self, monkeypatch):
        async def fake_ts(*args, timeout=30.0):
            return 0, ""

        monkeypatch.setattr(ra, "_ts", fake_ts)
        ra._write_config({"enabled": True, "https": True})
        await ra.disable()
        assert json.loads(ra.CONFIG_PATH.read_text())["https"] is False
        assert (await ra.status())["https_url"] == ""
