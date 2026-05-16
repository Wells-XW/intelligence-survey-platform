"""In-memory connection manager for real-time collaboration WebSockets.

Tracks every active WebSocket per survey, broadcasts presence and save
events, and maintains short-lived "focus locks" so the UI can show who
is currently editing which question.

This is an MVP single-process implementation.  When the API runs behind
multiple workers, swap the in-memory dict for a Redis pub/sub backend
without changing the public interface.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Soft-lock TTL — focus auto-releases after this many seconds with no
# heartbeat.  Frontend should ping every 30s; 60s gives one missed beat
# of grace before release.
FOCUS_TTL_SECONDS = 60

# Stable colour palette used to tag collaborator avatars.  Cycles when
# more than 8 collaborators are online (rare for survey design).
COLLAB_COLORS = (
    "#0EA5E9",  # sky-500
    "#22C55E",  # green-500
    "#F59E0B",  # amber-500
    "#EC4899",  # pink-500
    "#8B5CF6",  # violet-500
    "#14B8A6",  # teal-500
    "#F97316",  # orange-500
    "#EF4444",  # red-500
)


@dataclass
class Collaborator:
    """One live WebSocket connection with its presence metadata."""

    connection_id: str
    user_id: str
    display_name: str
    color: str
    websocket: WebSocket
    joined_at: datetime
    focused_question_id: Optional[str] = None
    focus_expires_at: Optional[datetime] = None
    last_heartbeat_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_presence(self) -> dict[str, Any]:
        """Serialise public presence info (no websocket / no internal IDs)."""
        return {
            "connection_id": self.connection_id,
            "user_id": self.user_id,
            "display_name": self.display_name,
            "color": self.color,
            "focused_question_id": self.focused_question_id,
            "focus_expires_at": (
                self.focus_expires_at.isoformat()
                if self.focus_expires_at
                else None
            ),
            "joined_at": self.joined_at.isoformat(),
        }


class ConnectionManager:
    """Tracks active WebSocket connections grouped by survey id."""

    def __init__(self) -> None:
        # survey_id -> connection_id -> Collaborator
        self._rooms: dict[str, dict[str, Collaborator]] = {}
        self._lock = asyncio.Lock()

    # ── Connection lifecycle ────────────────────────────────────────

    async def connect(
        self,
        websocket: WebSocket,
        survey_id: str,
        user_id: str,
        display_name: str,
    ) -> Collaborator:
        """Register a new connection, send presence snapshot, broadcast join.

        The websocket is assumed to be already accepted by the caller.
        """
        connection_id = secrets.token_urlsafe(8)

        async with self._lock:
            room = self._rooms.setdefault(survey_id, {})
            color = COLLAB_COLORS[len(room) % len(COLLAB_COLORS)]
            collab = Collaborator(
                connection_id=connection_id,
                user_id=user_id,
                display_name=display_name,
                color=color,
                websocket=websocket,
                joined_at=datetime.now(timezone.utc),
            )
            room[connection_id] = collab
            snapshot = [c.to_presence() for c in room.values()]

        # Send full snapshot to the joining user (includes themselves).
        await self._safe_send(
            collab,
            {"type": "presence.snapshot", "users": snapshot},
        )

        # Tell everyone else that someone joined.
        await self._broadcast(
            survey_id,
            {"type": "presence.join", "user": collab.to_presence()},
            exclude_connection_id=connection_id,
        )
        logger.info(
            "ws_connect survey=%s user=%s conn=%s",
            survey_id,
            user_id,
            connection_id,
        )
        return collab

    async def disconnect(self, survey_id: str, connection_id: str) -> None:
        """Remove a connection and broadcast its departure."""
        collab: Optional[Collaborator] = None
        async with self._lock:
            room = self._rooms.get(survey_id)
            if room and connection_id in room:
                collab = room.pop(connection_id)
                if not room:
                    self._rooms.pop(survey_id, None)
        if collab is None:
            return
        await self._broadcast(
            survey_id,
            {
                "type": "presence.leave",
                "connection_id": connection_id,
                "user_id": collab.user_id,
            },
        )
        logger.info(
            "ws_disconnect survey=%s user=%s conn=%s",
            survey_id,
            collab.user_id,
            connection_id,
        )

    # ── Focus locks ─────────────────────────────────────────────────

    async def acquire_focus(
        self,
        survey_id: str,
        connection_id: str,
        question_id: Optional[str],
    ) -> None:
        """Mark a connection as editing ``question_id`` and broadcast it."""
        async with self._lock:
            room = self._rooms.get(survey_id, {})
            collab = room.get(connection_id)
            if not collab:
                return
            collab.focused_question_id = question_id
            if question_id:
                collab.focus_expires_at = datetime.now(timezone.utc) + (
                    _ttl_delta()
                )
            else:
                collab.focus_expires_at = None
            payload = {
                "type": "focus.update",
                "connection_id": connection_id,
                "user_id": collab.user_id,
                "display_name": collab.display_name,
                "color": collab.color,
                "question_id": collab.focused_question_id,
                "expires_at": (
                    collab.focus_expires_at.isoformat()
                    if collab.focus_expires_at
                    else None
                ),
            }
        await self._broadcast(survey_id, payload)

    async def heartbeat(self, survey_id: str, connection_id: str) -> None:
        """Refresh focus TTL and last-seen timestamp on a heartbeat."""
        async with self._lock:
            room = self._rooms.get(survey_id, {})
            collab = room.get(connection_id)
            if not collab:
                return
            collab.last_heartbeat_at = datetime.now(timezone.utc)
            if collab.focused_question_id:
                collab.focus_expires_at = (
                    datetime.now(timezone.utc) + _ttl_delta()
                )

    async def reap_expired_focus(self, survey_id: str) -> None:
        """Drop expired focus locks and broadcast updates."""
        now = datetime.now(timezone.utc)
        expired: list[Collaborator] = []
        async with self._lock:
            room = self._rooms.get(survey_id, {})
            for collab in room.values():
                if (
                    collab.focused_question_id
                    and collab.focus_expires_at
                    and collab.focus_expires_at < now
                ):
                    collab.focused_question_id = None
                    collab.focus_expires_at = None
                    expired.append(collab)
        for collab in expired:
            await self._broadcast(
                survey_id,
                {
                    "type": "focus.update",
                    "connection_id": collab.connection_id,
                    "user_id": collab.user_id,
                    "display_name": collab.display_name,
                    "color": collab.color,
                    "question_id": None,
                    "expires_at": None,
                },
            )

    # ── Save broadcast ──────────────────────────────────────────────

    async def broadcast_saved(
        self,
        survey_id: str,
        version: int,
        actor_user_id: str,
        actor_connection_id: Optional[str] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        """Notify everyone that the survey was saved.

        ``actor_connection_id`` is the WebSocket the saver was using; we
        skip it because that user already saw the success toast and has
        the new version locally.  HTTP-only saves pass ``None`` so all
        live connections receive the broadcast.
        """
        payload = {
            "type": "survey.saved",
            "version": version,
            "actor_user_id": actor_user_id,
            "updated_at": (updated_at or datetime.now(timezone.utc)).isoformat(),
        }
        await self._broadcast(
            survey_id,
            payload,
            exclude_connection_id=actor_connection_id,
        )

    # ── Inspection helpers ──────────────────────────────────────────

    def get_users(self, survey_id: str) -> list[dict[str, Any]]:
        """Return public presence list (used by tests / introspection)."""
        room = self._rooms.get(survey_id, {})
        return [c.to_presence() for c in room.values()]

    def room_size(self, survey_id: str) -> int:
        return len(self._rooms.get(survey_id, {}))

    # ── Internals ───────────────────────────────────────────────────

    async def _broadcast(
        self,
        survey_id: str,
        message: dict[str, Any],
        exclude_connection_id: Optional[str] = None,
    ) -> None:
        async with self._lock:
            collaborators = list(self._rooms.get(survey_id, {}).values())
        targets = [
            c for c in collaborators if c.connection_id != exclude_connection_id
        ]
        if not targets:
            return
        await asyncio.gather(
            *(self._safe_send(c, message) for c in targets),
            return_exceptions=True,
        )

    async def _safe_send(
        self, collab: Collaborator, message: dict[str, Any]
    ) -> None:
        try:
            await collab.websocket.send_json(message)
        except Exception:  # noqa: BLE001 — best-effort delivery
            # Connection likely dropped; let the WS endpoint clean up.
            logger.debug(
                "ws_send_failed survey conn=%s", collab.connection_id
            )


def _ttl_delta():
    """Return the focus-lock TTL as a timedelta (testable seam)."""
    from datetime import timedelta

    return timedelta(seconds=FOCUS_TTL_SECONDS)


# Module-level singleton.  Routes import this and call its methods.
manager = ConnectionManager()
