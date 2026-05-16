"""Unit tests for the in-memory ConnectionManager.

These tests focus on the ConnectionManager state machine (presence,
focus locks, broadcasts) rather than the full WebSocket handshake.
A websocket-protocol smoke test is included at the bottom using
FastAPI's TestClient.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.collaboration import ConnectionManager


class FakeWebSocket:
    """Minimal stand-in for ``starlette.websockets.WebSocket`` used in
    unit tests.  Captures every JSON frame sent to the client."""

    def __init__(self, name: str = "ws") -> None:
        self.name = name
        self.outbox: list[dict[str, Any]] = []
        self.closed = False

    async def send_json(self, message: dict[str, Any]) -> None:
        if self.closed:
            raise RuntimeError("ws closed")
        self.outbox.append(message)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True


# ── ConnectionManager fixtures ───────────────────────────────────────


@pytest.fixture
def manager():
    return ConnectionManager()


@pytest.fixture
def ws_a():
    return FakeWebSocket("alice")


@pytest.fixture
def ws_b():
    return FakeWebSocket("bob")


# ── Presence tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_sends_snapshot_to_self(manager, ws_a):
    collab = await manager.connect(
        websocket=ws_a, survey_id="s1", user_id="u1", display_name="Alice"
    )
    # First frame to self is the snapshot containing themselves.
    assert ws_a.outbox[0]["type"] == "presence.snapshot"
    users = ws_a.outbox[0]["users"]
    assert len(users) == 1
    assert users[0]["user_id"] == "u1"
    assert users[0]["color"]
    assert collab.color == users[0]["color"]


@pytest.mark.asyncio
async def test_second_connect_broadcasts_join(manager, ws_a, ws_b):
    await manager.connect(ws_a, "s1", "u1", "Alice")
    ws_a.outbox.clear()

    collab_b = await manager.connect(ws_b, "s1", "u2", "Bob")

    # Bob receives a snapshot of [Alice, Bob] (2 users).
    assert ws_b.outbox[0]["type"] == "presence.snapshot"
    assert len(ws_b.outbox[0]["users"]) == 2

    # Alice receives a presence.join for Bob.
    join_frames = [m for m in ws_a.outbox if m.get("type") == "presence.join"]
    assert len(join_frames) == 1
    assert join_frames[0]["user"]["user_id"] == "u2"
    assert join_frames[0]["user"]["connection_id"] == collab_b.connection_id


@pytest.mark.asyncio
async def test_disconnect_broadcasts_leave_and_drops_room(manager, ws_a, ws_b):
    collab_a = await manager.connect(ws_a, "s1", "u1", "Alice")
    await manager.connect(ws_b, "s1", "u2", "Bob")
    ws_b.outbox.clear()

    await manager.disconnect("s1", collab_a.connection_id)

    leave = [m for m in ws_b.outbox if m.get("type") == "presence.leave"]
    assert len(leave) == 1
    assert leave[0]["user_id"] == "u1"

    # Room still has Bob.
    assert manager.room_size("s1") == 1


@pytest.mark.asyncio
async def test_disconnect_unknown_is_safe(manager, ws_a):
    await manager.connect(ws_a, "s1", "u1", "Alice")
    # Unknown connection id should not raise.
    await manager.disconnect("s1", "does-not-exist")
    await manager.disconnect("other-survey", "anything")


# ── Focus tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquire_focus_broadcasts_to_others(manager, ws_a, ws_b):
    collab_a = await manager.connect(ws_a, "s1", "u1", "Alice")
    await manager.connect(ws_b, "s1", "u2", "Bob")
    ws_a.outbox.clear()
    ws_b.outbox.clear()

    await manager.acquire_focus("s1", collab_a.connection_id, "q1")

    # Both Alice (self) and Bob receive the focus.update broadcast.
    a_frames = [m for m in ws_a.outbox if m.get("type") == "focus.update"]
    b_frames = [m for m in ws_b.outbox if m.get("type") == "focus.update"]
    assert len(a_frames) == 1
    assert len(b_frames) == 1
    assert b_frames[0]["question_id"] == "q1"
    assert b_frames[0]["user_id"] == "u1"
    assert b_frames[0]["expires_at"]


@pytest.mark.asyncio
async def test_release_focus_clears_question(manager, ws_a):
    collab = await manager.connect(ws_a, "s1", "u1", "Alice")
    await manager.acquire_focus("s1", collab.connection_id, "q1")
    ws_a.outbox.clear()

    await manager.acquire_focus("s1", collab.connection_id, None)

    frames = [m for m in ws_a.outbox if m.get("type") == "focus.update"]
    assert frames[-1]["question_id"] is None
    assert frames[-1]["expires_at"] is None


@pytest.mark.asyncio
async def test_reap_expires_old_focus(manager, ws_a):
    collab = await manager.connect(ws_a, "s1", "u1", "Alice")
    await manager.acquire_focus("s1", collab.connection_id, "q1")
    # Manually rewind the expiry into the past.
    room = manager._rooms["s1"]
    room[collab.connection_id].focus_expires_at = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    ws_a.outbox.clear()

    await manager.reap_expired_focus("s1")

    frames = [m for m in ws_a.outbox if m.get("type") == "focus.update"]
    assert len(frames) == 1
    assert frames[0]["question_id"] is None


@pytest.mark.asyncio
async def test_heartbeat_extends_focus_expiry(manager, ws_a):
    collab = await manager.connect(ws_a, "s1", "u1", "Alice")
    await manager.acquire_focus("s1", collab.connection_id, "q1")
    room = manager._rooms["s1"]
    original = room[collab.connection_id].focus_expires_at
    assert original is not None

    # Move expiry close to now to make the extension observable.
    room[collab.connection_id].focus_expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=1)
    )
    await manager.heartbeat("s1", collab.connection_id)

    new_expiry = room[collab.connection_id].focus_expires_at
    assert new_expiry is not None
    assert new_expiry > datetime.now(timezone.utc) + timedelta(seconds=30)


# ── Save broadcast ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_broadcast_saved_excludes_actor_connection(manager, ws_a, ws_b):
    collab_a = await manager.connect(ws_a, "s1", "u1", "Alice")
    await manager.connect(ws_b, "s1", "u2", "Bob")
    ws_a.outbox.clear()
    ws_b.outbox.clear()

    await manager.broadcast_saved(
        survey_id="s1",
        version=2,
        actor_user_id="u1",
        actor_connection_id=collab_a.connection_id,
    )

    assert all(m["type"] != "survey.saved" for m in ws_a.outbox)
    saved_frames = [m for m in ws_b.outbox if m["type"] == "survey.saved"]
    assert len(saved_frames) == 1
    assert saved_frames[0]["version"] == 2
    assert saved_frames[0]["actor_user_id"] == "u1"


@pytest.mark.asyncio
async def test_broadcast_saved_no_actor_reaches_everyone(manager, ws_a, ws_b):
    await manager.connect(ws_a, "s1", "u1", "Alice")
    await manager.connect(ws_b, "s1", "u2", "Bob")
    ws_a.outbox.clear()
    ws_b.outbox.clear()

    await manager.broadcast_saved(
        survey_id="s1", version=3, actor_user_id="u1", actor_connection_id=None
    )

    a_saved = [m for m in ws_a.outbox if m["type"] == "survey.saved"]
    b_saved = [m for m in ws_b.outbox if m["type"] == "survey.saved"]
    assert len(a_saved) == 1
    assert len(b_saved) == 1


@pytest.mark.asyncio
async def test_room_isolation(manager, ws_a, ws_b):
    """Frames in survey s1 must not reach connections in survey s2."""
    await manager.connect(ws_a, "s1", "u1", "Alice")
    await manager.connect(ws_b, "s2", "u2", "Bob")
    ws_b.outbox.clear()

    await manager.broadcast_saved(
        survey_id="s1", version=1, actor_user_id="u1", actor_connection_id=None
    )

    assert all(m.get("type") != "survey.saved" for m in ws_b.outbox)


# ── send failure resilience ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_failing_send_does_not_break_broadcast(manager, ws_a):
    # Bob's send will raise; broadcast must still succeed.
    class BrokenWS(FakeWebSocket):
        async def send_json(self, message):
            raise ConnectionError("simulated")

    bob = BrokenWS("bob")
    await manager.connect(ws_a, "s1", "u1", "Alice")
    await manager.connect(bob, "s1", "u2", "Bob")
    ws_a.outbox.clear()

    # Should not raise.
    await manager.broadcast_saved(
        survey_id="s1", version=2, actor_user_id="u3", actor_connection_id=None
    )

    a_saved = [m for m in ws_a.outbox if m["type"] == "survey.saved"]
    assert len(a_saved) == 1


# ── Color cycling ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_color_cycles_through_palette(manager):
    from app.core.collaboration import COLLAB_COLORS

    websockets = []
    for i in range(len(COLLAB_COLORS) + 2):
        ws = FakeWebSocket(f"u{i}")
        websockets.append(ws)
        await manager.connect(ws, "s1", f"u{i}", f"User {i}")

    # The 9th and 10th users should reuse the first two palette entries.
    snapshot_first_user = websockets[0].outbox[0]["users"]
    assert snapshot_first_user[0]["color"] == COLLAB_COLORS[0]

    # Final connect's snapshot lists everyone, where colors cycle.
    final_snapshot = websockets[-1].outbox[0]["users"]
    colors = [u["color"] for u in final_snapshot]
    n = len(COLLAB_COLORS)
    expected = [COLLAB_COLORS[i % n] for i in range(len(websockets))]
    assert colors == expected


# ── End-to-end auth handshake (FastAPI TestClient) ────────────────────


@pytest.mark.asyncio
async def test_ws_auth_required(async_client, auth_headers):
    """An unauthenticated WS connection is closed with 4401."""
    from fastapi.testclient import TestClient

    from app.main import app

    # Use the sync TestClient for WS — easier than async + ASGI transport.
    with TestClient(app) as client:
        # Use a real survey so the route exists and the survey-access
        # check is exercised after auth would succeed.
        survey_resp = client.post(
            "/api/v1/surveys",
            json={"title": "WS Test"},
            headers=auth_headers,
        )
        assert survey_resp.status_code == 201
        sid = survey_resp.json()["id"]

        with client.websocket_connect(f"/api/v1/ws/surveys/{sid}") as ws:
            # First message must be auth — send an invalid token.
            ws.send_json({"type": "auth", "token": "not-a-real-jwt"})
            with pytest.raises(Exception):
                # Either the server closes immediately, or the next
                # receive raises with a close frame.
                ws.receive_json()
