"""Regressionstests zu T6-02 bis T6-08 der Code-Analyse (docs/analyse/T6-...).

FTP-Anmeldebremse und Adressprüfung am virtuellen Drucker, FTP-Datenproxy in beide Richtungen, endliche Zahlen
bei Bewegungsbefehlen, Größengrenze für Druckerdateien im Speicher, Weiterleitungen und Größe beim Kamera-Abruf.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from httpx import AsyncClient

from backend.app.services.virtual_printer.auth_limiter import AuthRateLimiter
from backend.app.services.virtual_printer.ftp_server import FTPSession

ACCESS_CODE = "13572468"


class _Writer:
    """Just enough of an asyncio.StreamWriter for the FTP session."""

    def __init__(self, peer=("10.0.0.5", 40000)):
        self.buf = bytearray()
        self.peer = peer
        self.closed = False

    def get_extra_info(self, key):
        return {"peername": self.peer, "sockname": ("10.0.0.2", 990)}.get(key)

    def write(self, data):
        self.buf += data

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


async def _ftp_session(tmp_path, commands: bytes, limiter: AuthRateLimiter, peer=("10.0.0.5", 40000)) -> str:
    reader = asyncio.StreamReader()
    writer = _Writer(peer)
    session = FTPSession(reader, writer, tmp_path, ACCESS_CODE, MagicMock(), None, auth_limiter=limiter)
    reader.feed_data(commands)
    reader.feed_eof()
    await session.handle()
    return writer.buf.decode()


class TestAuthRateLimiter:
    def test_blocks_after_the_allowance_and_recovers_when_the_window_passes(self):
        now = [0.0]
        limiter = AuthRateLimiter(max_attempts=5, window_seconds=60, clock=lambda: now[0])
        for _ in range(4):
            limiter.record_failure("10.0.0.5")
        assert not limiter.is_blocked("10.0.0.5")
        limiter.record_failure("10.0.0.5")
        assert limiter.is_blocked("10.0.0.5")
        assert not limiter.is_blocked("10.0.0.6"), "other addresses are unaffected"
        now[0] = 61.0
        assert not limiter.is_blocked("10.0.0.5")
        assert limiter._failures == {}, "expired entries are pruned"

    def test_a_successful_login_clears_the_count(self):
        limiter = AuthRateLimiter()
        for _ in range(4):
            limiter.record_failure("10.0.0.5")
        limiter.clear("10.0.0.5")
        limiter.record_failure("10.0.0.5")
        assert not limiter.is_blocked("10.0.0.5")


class TestFtpLoginRateLimit:
    @pytest.mark.asyncio
    async def test_guessing_stops_after_five_failures_and_the_connection_is_closed(self, tmp_path):
        guesses = b"".join(b"PASS %08d\r\n" % i for i in range(200))
        out = await _ftp_session(
            tmp_path, b"USER bblp\r\n" + guesses + b"PASS " + ACCESS_CODE.encode() + b"\r\n", AuthRateLimiter()
        )

        assert out.count("530 Login incorrect") == 5
        assert out.count("421 Too many failed logins") == 1, "told once, then disconnected"
        assert "230 Login successful" not in out, "the right code after the lockout is not even looked at"

    @pytest.mark.asyncio
    async def test_the_count_survives_a_reconnect(self, tmp_path):
        limiter = AuthRateLimiter()
        for _ in range(5):
            await _ftp_session(tmp_path, b"USER bblp\r\nPASS 00000000\r\n", limiter)

        out = await _ftp_session(tmp_path, b"USER bblp\r\nPASS " + ACCESS_CODE.encode() + b"\r\n", limiter)

        assert "421 Too many failed logins" in out and "230" not in out

    @pytest.mark.asyncio
    async def test_a_typo_or_two_does_not_lock_anyone_out(self, tmp_path):
        out = await _ftp_session(
            tmp_path,
            b"USER bblp\r\nPASS 00000000\r\nPASS 11111111\r\nPASS " + ACCESS_CODE.encode() + b"\r\n",
            AuthRateLimiter(),
        )
        assert out.count("530 Login incorrect") == 2
        assert "230 Login successful" in out

    @pytest.mark.asyncio
    async def test_another_address_is_not_locked_out(self, tmp_path):
        limiter = AuthRateLimiter()
        await _ftp_session(tmp_path, b"USER bblp\r\n" + b"PASS 00000000\r\n" * 6, limiter, peer=("10.0.0.66", 1))

        out = await _ftp_session(tmp_path, b"USER bblp\r\nPASS " + ACCESS_CODE.encode() + b"\r\n", limiter)

        assert "230 Login successful" in out


class TestFtpDataConnectionPeer:
    def _session(self, tmp_path) -> FTPSession:
        session = FTPSession(
            asyncio.StreamReader(), _Writer(("10.0.0.5", 40000)), tmp_path, ACCESS_CODE, MagicMock(), None
        )
        session.authenticated = True
        return session

    @pytest.mark.asyncio
    async def test_a_data_connection_from_another_host_is_closed_and_ignored(self, tmp_path):
        session = self._session(tmp_path)
        stranger = _Writer(("10.0.0.66", 51515))

        await asyncio.wait_for(session._handle_data_connection(asyncio.StreamReader(), stranger), 1)

        assert stranger.closed
        assert session._data_reader is None and not session._data_connected.is_set()

    @pytest.mark.asyncio
    async def test_the_rightful_client_can_still_connect_afterwards(self, tmp_path):
        session = self._session(tmp_path)
        await session._handle_data_connection(asyncio.StreamReader(), _Writer(("10.0.0.66", 51515)))
        own_reader = asyncio.StreamReader()
        own = _Writer(("10.0.0.5", 40001))

        task = asyncio.create_task(session._handle_data_connection(own_reader, own))
        await asyncio.sleep(0.05)

        assert session._data_reader is own_reader and session._data_connected.is_set()
        session._transfer_done.set()
        await task


class TestFtpDataProxy:
    """Proxy mode: the one-shot listener between slicer and printer."""

    async def _printer(self, handler):
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        return server, server.sockets[0].getsockname()[1]

    def _proxy(self, tmp_path):
        from backend.app.services.virtual_printer.tcp_proxy import FTPTLSProxy

        proxy = FTPTLSProxy("FTP", 0, "127.0.0.1", 990, tmp_path / "c", tmp_path / "k")
        proxy._data_servers = []
        proxy._auto_close_tasks = []
        return proxy

    async def _listen(self, proxy, printer_port, **kwargs) -> int:
        probe = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = probe.sockets[0].getsockname()[1]
        probe.close()
        await probe.wait_closed()
        await proxy._start_data_proxy_server(port, "127.0.0.1", printer_port, use_tls=False, **kwargs)
        return port

    async def _cleanup(self, proxy, *servers):
        for task in proxy._auto_close_tasks:
            task.cancel()
        for server in [*proxy._data_servers, *servers]:
            server.close()

    @pytest.mark.asyncio
    async def test_what_the_printer_sends_reaches_the_slicer(self, tmp_path):
        """T6-08: a download or listing through the proxy used to stay empty."""

        async def printer_side(_reader, writer):
            writer.write(b"-rw-r--r-- 1 root root 123 model.3mf\r\n")
            await writer.drain()
            writer.close()

        printer, printer_port = await self._printer(printer_side)
        proxy = self._proxy(tmp_path)
        port = await self._listen(proxy, printer_port)

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            data = await asyncio.wait_for(reader.read(), timeout=5)
        finally:
            writer.close()
            await self._cleanup(proxy, printer)

        assert data == b"-rw-r--r-- 1 root root 123 model.3mf\r\n"

    @pytest.mark.asyncio
    async def test_an_upload_still_arrives_complete_at_the_printer(self, tmp_path):
        received = bytearray()
        done = asyncio.Event()

        async def printer_side(reader, writer):
            while chunk := await reader.read(65536):
                received.extend(chunk)
            done.set()
            writer.close()

        printer, printer_port = await self._printer(printer_side)
        proxy = self._proxy(tmp_path)
        port = await self._listen(proxy, printer_port)
        payload = b"PK" + bytes(range(256)) * 2000

        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write(payload)
            await writer.drain()
            await asyncio.wait_for(done.wait(), timeout=5)
        finally:
            writer.close()
            await self._cleanup(proxy, printer)

        assert bytes(received) == payload

    @pytest.mark.asyncio
    async def test_a_stranger_is_turned_away_without_using_up_the_listener(self, tmp_path):
        """T6-03: the listener has no login; only the control connection's address may use it."""
        received = bytearray()
        done = asyncio.Event()

        async def printer_side(reader, writer):
            while chunk := await reader.read(65536):
                received.extend(chunk)
            done.set()
            writer.close()

        printer, printer_port = await self._printer(printer_side)
        proxy = self._proxy(tmp_path)
        port = await self._listen(proxy, printer_port, allowed_peer="10.9.9.9")

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"FREMDE DATEN")
        try:
            try:
                answer = await asyncio.wait_for(reader.read(), timeout=5)
            except ConnectionResetError:  # Windows reports the close as a reset when data was still unread
                answer = b""
            assert answer == b"", "closed straight away"
            assert not done.is_set() and not received, "nothing was passed on to the printer"
            assert proxy._data_servers[0].is_serving(), "the rightful client can still connect"
        finally:
            writer.close()
            await self._cleanup(proxy, printer)


class TestJogRejectsNonFiniteNumbers:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "/bed-jog?distance=nan",
            "/bed-jog?distance=inf",
            "/xy-jog?x=nan&y=0",
            "/xy-jog?x=1&y=-inf",
            "/extruder-jog?distance=NaN",
        ],
    )
    async def test_nothing_is_sent_to_the_printer(self, async_client: AsyncClient, printer_factory, url):
        printer = await printer_factory()
        client = MagicMock()
        client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as manager:
            manager.get_client.return_value = client
            resp = await async_client.post(f"/api/v1/printers/{printer.id}{url}")

        assert resp.status_code == 422, resp.text
        client.send_gcode.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_normal_jog_still_goes_out(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory()
        client = MagicMock()
        client.send_gcode.return_value = True
        with patch("backend.app.api.routes.printers.printer_manager") as manager:
            manager.get_client.return_value = client
            resp = await async_client.post(f"/api/v1/printers/{printer.id}/bed-jog?distance=5")

        assert resp.status_code == 200, resp.text
        client.send_gcode.assert_called_once_with("G91\nG1 Z5.00 F600\nG90")


class TestPrinterFilePreviewLimit:
    @pytest.mark.asyncio
    async def test_the_type_is_checked_before_anything_is_downloaded(self, async_client: AsyncClient, printer_factory):
        printer = await printer_factory()
        download = AsyncMock(return_value=b"\x00" * 1024)
        with patch("backend.app.api.routes.printers.download_file_bytes_async", new=download):
            resp = await async_client.get(f"/api/v1/printers/{printer.id}/files/gcode?path=/timelapse/video.mp4")

        assert resp.status_code == 400
        download.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "/files/gcode?path=/cache/a.gcode",
            "/files/plates?path=/cache/a.3mf",
            "/files/plate-thumbnail/1?path=/cache/a.3mf",
        ],
    )
    async def test_preview_routes_pass_a_size_cap_and_answer_413_when_it_is_hit(
        self, async_client: AsyncClient, printer_factory, url
    ):
        from backend.app.services.bambu_ftp import DownloadLimitExceeded

        printer = await printer_factory()
        download = AsyncMock(side_effect=DownloadLimitExceeded("/cache/a"))
        with patch("backend.app.api.routes.printers.download_file_bytes_async", new=download):
            resp = await async_client.get(f"/api/v1/printers/{printer.id}{url}")

        assert resp.status_code == 413, resp.text
        assert download.await_args.kwargs["max_bytes"] == 256 * 1024 * 1024

    def test_the_ftp_client_stops_reading_at_the_cap(self):
        from backend.app.services.bambu_ftp import BambuFTPClient, DownloadLimitExceeded

        client = BambuFTPClient.__new__(BambuFTPClient)
        delivered = []

        def retrbinary(_cmd, callback):
            for _ in range(100):
                callback(b"x" * 8192)
                delivered.append(8192)

        client._ftp = MagicMock(retrbinary=retrbinary)

        with pytest.raises(DownloadLimitExceeded):
            client.download_file("/timelapse/big.mp4", max_bytes=20_000)
        assert sum(delivered) <= 20_000, "aborted as soon as the cap would be exceeded"
        assert client.download_file("/cache/small.gcode", max_bytes=10_000_000) == b"x" * 819_200


class TestCameraFetch:
    async def _serve(self, routes: dict):
        app = web.Application()
        for path, handler in routes.items():
            app.router.add_get(path, handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        return runner, site._server.sockets[0].getsockname()[1]

    @pytest.fixture
    def lan_camera(self):
        """Let exactly one loopback URL pass as if it were a camera on the LAN; everything else is vetted for real."""
        from backend.app.services import external_camera

        real = external_camera._sanitize_camera_url
        allowed: list[str] = []

        def sanitize(url, schemes=("http", "https", "rtsp")):
            return url if url in allowed else real(url, schemes)

        with patch.object(external_camera, "_sanitize_camera_url", side_effect=sanitize):
            yield allowed

    @pytest.mark.asyncio
    async def test_a_redirect_to_a_refused_destination_is_not_followed(self, lan_camera):
        """T6-06: the camera answers 302 to loopback; the internal page must never be requested."""
        from backend.app.services import external_camera

        hits = []

        async def secret(_request):
            hits.append("secret")
            return web.Response(body=b"INTERNAL")

        internal, internal_port = await self._serve({"/secret": secret})

        async def redirect(_request):
            raise web.HTTPFound(f"http://127.0.0.1:{internal_port}/secret")

        camera, camera_port = await self._serve({"/snap.jpg": redirect})
        cam_url = f"http://127.0.0.1:{camera_port}/snap.jpg"
        lan_camera.append(cam_url)
        try:
            assert await external_camera._capture_snapshot(cam_url, 5) is None
            assert await external_camera._capture_mjpeg_frame(cam_url, 5) is None
            assert [frame async for frame in external_camera._stream_mjpeg(cam_url)] == []
        finally:
            await internal.cleanup()
            await camera.cleanup()

        assert hits == []

    @pytest.mark.asyncio
    async def test_a_redirect_to_an_allowed_destination_still_works(self, lan_camera):
        from backend.app.services import external_camera

        jpeg = b"\xff\xd8" + b"\x00" * 64 + b"\xff\xd9"

        async def image(_request):
            return web.Response(body=jpeg, content_type="image/jpeg")

        async def redirect(_request):
            raise web.HTTPFound("/real.jpg")

        camera, port = await self._serve({"/snap.jpg": redirect, "/real.jpg": image})
        cam_url = f"http://127.0.0.1:{port}/snap.jpg"
        lan_camera.extend([cam_url, f"http://127.0.0.1:{port}/real.jpg"])
        try:
            assert await external_camera._capture_snapshot(cam_url, 5) == jpeg
        finally:
            await camera.cleanup()

    @pytest.mark.asyncio
    async def test_an_endless_redirect_chain_gives_up(self, lan_camera):
        from backend.app.services import external_camera

        hops = []

        async def loop(request):
            hops.append(request.path)
            raise web.HTTPFound("/snap.jpg")

        camera, port = await self._serve({"/snap.jpg": loop})
        cam_url = f"http://127.0.0.1:{port}/snap.jpg"
        lan_camera.append(cam_url)
        try:
            assert await external_camera._capture_snapshot(cam_url, 5) is None
        finally:
            await camera.cleanup()
        assert len(hops) == external_camera._MAX_REDIRECTS + 1

    @pytest.mark.asyncio
    async def test_a_snapshot_larger_than_the_cap_is_dropped(self, lan_camera, monkeypatch):
        from backend.app.services import external_camera

        monkeypatch.setattr(external_camera, "_MAX_SNAPSHOT_BYTES", 100_000)

        async def big(_request):
            return web.Response(body=b"\xff\xd8" + b"\x00" * 300_000)

        async def small(_request):
            return web.Response(body=b"\xff\xd8" + b"\x00" * 50_000)

        camera, port = await self._serve({"/big.jpg": big, "/small.jpg": small})
        urls = [f"http://127.0.0.1:{port}/big.jpg", f"http://127.0.0.1:{port}/small.jpg"]
        lan_camera.extend(urls)
        try:
            assert await external_camera._capture_snapshot(urls[0], 5) is None
            assert len(await external_camera._capture_snapshot(urls[1], 5)) == 50_002
        finally:
            await camera.cleanup()
