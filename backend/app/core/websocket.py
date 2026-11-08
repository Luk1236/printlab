import asyncio
import json
import time
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """Manages WebSocket connections and broadcasts with concurrent fan-out and slow-client isolation."""

    def __init__(self, send_timeout: float = 2.0):
        self.active_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()
        self.send_timeout: float = send_timeout
        self.total_broadcasts: int = 0
        self.total_messages_sent: int = 0
        self.dropped_connections: int = 0
        self.last_broadcast_ms: float = 0.0
        self.max_broadcast_ms: float = 0.0
        self._cumulative_broadcast_ms: float = 0.0

    def reset_metrics(self) -> None:
        """Reset broadcast telemetry counters."""
        self.total_broadcasts = 0
        self.total_messages_sent = 0
        self.dropped_connections = 0
        self.last_broadcast_ms = 0.0
        self.max_broadcast_ms = 0.0
        self._cumulative_broadcast_ms = 0.0

    def get_metrics(self) -> dict[str, Any]:
        """Return live WebSocket fan-out performance and health telemetry."""
        avg_ms = self._cumulative_broadcast_ms / self.total_broadcasts if self.total_broadcasts > 0 else 0.0
        return {
            "active_connections": len(self.active_connections),
            "total_broadcasts": self.total_broadcasts,
            "total_messages_sent": self.total_messages_sent,
            "dropped_connections": self.dropped_connections,
            "last_broadcast_ms": round(self.last_broadcast_ms, 3),
            "avg_broadcast_ms": round(avg_ms, 3),
            "max_broadcast_ms": round(self.max_broadcast_ms, 3),
        }

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def _send_with_timeout(self, connection: WebSocket, data: str) -> WebSocket | None:
        """Send payload to a single client with timeout protection; returns connection on failure."""
        try:
            await asyncio.wait_for(connection.send_text(data), timeout=self.send_timeout)
            return None
        except Exception:
            return connection

    async def _fanout(self, targets: list[WebSocket], data: str) -> None:
        """Concurrently deliver *data* to *targets* outside the connection lock and prune failed sockets."""
        if not targets:
            return

        t0 = time.perf_counter()
        results = await asyncio.gather(*(self._send_with_timeout(conn, data) for conn in targets))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        disconnected = [conn for conn in results if conn is not None]
        delivered = len(targets) - len(disconnected)

        self.total_broadcasts += 1
        self.total_messages_sent += delivered
        self.last_broadcast_ms = elapsed_ms
        self._cumulative_broadcast_ms += elapsed_ms
        if elapsed_ms > self.max_broadcast_ms:
            self.max_broadcast_ms = elapsed_ms

        if disconnected:
            async with self._lock:
                for conn in disconnected:
                    if conn in self.active_connections:
                        self.active_connections.remove(conn)
                        self.dropped_connections += 1

    async def broadcast(self, message: dict[str, Any]):
        """Broadcast a message concurrently to all connected clients."""
        if not self.active_connections:
            return

        data = json.dumps(message)
        async with self._lock:
            targets = list(self.active_connections)

        await self._fanout(targets, data)

    async def broadcast_to_user(self, user_id: int | None, message: dict[str, Any]):
        """Send a message to every connection authenticated as the given user.

        When ``user_id`` is None the message fans out to all connections —
        this is the auth-disabled single-user path, where neither the queue
        item's ``created_by_id`` nor the WS principal is set, and the
        existing fan-out semantics are exactly what the user wants.

        Per-user routing reads ``websocket.state.printlab_principal_user_id``
        stamped at connect time (``routes/websocket.py``). Connections
        without a stamped id are skipped on the targeted path so an
        anonymous reader never receives another user's dispatch toast.
        """
        if user_id is None:
            await self.broadcast(message)
            return

        if not self.active_connections:
            return

        data = json.dumps(message)
        async with self._lock:
            targets = [
                conn
                for conn in self.active_connections
                if getattr(getattr(conn, "state", None), "printlab_principal_user_id", None) == user_id
            ]

        await self._fanout(targets, data)

    async def send_printer_status(self, printer_id: int, status: dict):
        """Send printer status update to all clients."""
        await self.broadcast(
            {
                "type": "printer_status",
                "printer_id": printer_id,
                "data": status,
            }
        )

    async def send_print_start(self, printer_id: int, data: dict):
        """Notify clients that a print has started."""
        await self.broadcast(
            {
                "type": "print_start",
                "printer_id": printer_id,
                "data": data,
            }
        )

    async def send_print_complete(self, printer_id: int, data: dict):
        """Notify clients that a print has completed."""
        await self.broadcast(
            {
                "type": "print_complete",
                "printer_id": printer_id,
                "data": data,
            }
        )

    async def send_print_confirm_request(self, printer_id: int, data: dict):
        """Ask connected clients for a post-print outcome verdict (#1898)."""
        await self.broadcast(
            {
                "type": "print_confirm_request",
                "printer_id": printer_id,
                "data": data,
            }
        )

    async def send_archive_created(self, archive: dict):
        """Notify clients that a new archive was created."""
        await self.broadcast(
            {
                "type": "archive_created",
                "data": archive,
            }
        )

    async def send_archive_updated(self, archive: dict):
        """Notify clients that an archive was updated."""
        await self.broadcast(
            {
                "type": "archive_updated",
                "data": archive,
            }
        )

    async def send_queue_item_uploading(
        self,
        user_id: int | None,
        queue_item_id: int,
        printer_id: int,
        printer_name: str | None,
        file_name: str,
        total_bytes: int,
    ):
        """Toast trigger: scheduler picked the item up, FTP upload starts."""
        await self.broadcast_to_user(
            user_id,
            {
                "type": "queue_item_uploading",
                "queue_item_id": queue_item_id,
                "printer_id": printer_id,
                "printer_name": printer_name,
                "file_name": file_name,
                "total_bytes": total_bytes,
            },
        )

    async def send_queue_item_upload_progress(
        self,
        user_id: int | None,
        queue_item_id: int,
        bytes_transferred: int,
        total_bytes: int,
    ):
        """Toast update: throttled byte-level progress during the FTP upload."""
        pct = int(round(100 * bytes_transferred / total_bytes)) if total_bytes else 0
        await self.broadcast_to_user(
            user_id,
            {
                "type": "queue_item_upload_progress",
                "queue_item_id": queue_item_id,
                "bytes_transferred": bytes_transferred,
                "total_bytes": total_bytes,
                "pct": pct,
            },
        )

    async def send_queue_item_acked(
        self,
        user_id: int | None,
        queue_item_id: int,
        printer_id: int,
    ):
        """Toast trigger: watchdog confirmed the printer transitioned out of pre_state."""
        await self.broadcast_to_user(
            user_id,
            {
                "type": "queue_item_acked",
                "queue_item_id": queue_item_id,
                "printer_id": printer_id,
            },
        )

    async def send_queue_item_failed(
        self,
        user_id: int | None,
        queue_item_id: int,
        printer_id: int | None,
        reason: str,
    ):
        """Toast trigger: dispatch failed at any stage. Toast turns red, auto-dismisses."""
        await self.broadcast_to_user(
            user_id,
            {
                "type": "queue_item_failed",
                "queue_item_id": queue_item_id,
                "printer_id": printer_id,
                "reason": reason,
            },
        )

    async def send_missing_spool_assignment(
        self,
        printer_id: int,
        printer_name: str,
        missing_slots: list[dict[str, str]],
    ):
        """Notify clients that a print started with missing spool assignments."""
        await self.broadcast(
            {
                "type": "missing_spool_assignment",
                "printer_id": printer_id,
                "printer_name": printer_name,
                "missing_slots": missing_slots,
            }
        )


# Global connection manager
ws_manager = ConnectionManager()
