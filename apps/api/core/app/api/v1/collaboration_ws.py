"""WebSocket endpoint for real-time survey collaboration.

Protocol (JSON messages):

    Client → Server
        {"type": "auth", "token": "<JWT>"}
        {"type": "focus.acquire", "question_id": "..."}
        {"type": "focus.release"}
        {"type": "heartbeat"}

    Server → Client
        {"type": "presence.snapshot", "users": [...]}
        {"type": "presence.join", "user": {...}}
        {"type": "presence.leave", "user_id": "...", "connection_id": "..."}
        {"type": "focus.update", "user_id": "...", "question_id": "...|null", ...}
        {"type": "survey.saved", "version": N, "actor_user_id": "...", "updated_at": "..."}
        {"type": "error", "code": "auth_required|unauthorized|invalid", "detail": "..."}

The first message MUST be ``auth``.  Any other message before auth, or
an invalid token, closes the connection with code 4401.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ...core.collaboration import manager
from ...core.security import decode_token
from ...database import async_session
from ...models import SurveyPermission, User

logger = logging.getLogger(__name__)

router = APIRouter()

# Close codes (4xxx range is reserved for application use)
WS_CLOSE_AUTH = 4401
WS_CLOSE_FORBIDDEN = 4403
WS_CLOSE_NOT_FOUND = 4404
WS_CLOSE_PROTOCOL = 4400

# How often the server sweeps expired focus locks for a room.
FOCUS_REAP_INTERVAL_SECONDS = 15


async def _authenticate_user(token: str) -> Optional[User]:
    """Decode the JWT and load the user, or return None on any failure."""
    try:
        payload = decode_token(token)
    except Exception:
        return None
    if payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user and user.is_active:
            return user
        return None


async def _has_survey_access(survey_id: str, user_id: str) -> bool:
    """True if the user has any role on the survey (viewer or above)."""
    async with async_session() as session:
        result = await session.execute(
            select(SurveyPermission).where(
                SurveyPermission.survey_id == survey_id,
                SurveyPermission.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None


@router.websocket("/ws/surveys/{survey_id}")
async def collaboration_socket(websocket: WebSocket, survey_id: str) -> None:
    """Long-lived WebSocket carrying presence + focus + save events."""
    await websocket.accept()

    # ── Step 1: expect first message to be `auth` ───────────────────
    try:
        first_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
    except (asyncio.TimeoutError, WebSocketDisconnect):
        await websocket.close(code=WS_CLOSE_AUTH, reason="auth timeout")
        return
    except Exception:
        await websocket.close(code=WS_CLOSE_PROTOCOL, reason="invalid auth frame")
        return

    if not isinstance(first_msg, dict) or first_msg.get("type") != "auth":
        await websocket.close(
            code=WS_CLOSE_PROTOCOL, reason="first message must be auth"
        )
        return

    token = first_msg.get("token")
    if not token or not isinstance(token, str):
        await websocket.close(code=WS_CLOSE_AUTH, reason="missing token")
        return

    user = await _authenticate_user(token)
    if user is None:
        await websocket.close(code=WS_CLOSE_AUTH, reason="invalid token")
        return

    if not await _has_survey_access(survey_id, user.id):
        await websocket.close(code=WS_CLOSE_FORBIDDEN, reason="no access")
        return

    collab = await manager.connect(
        websocket=websocket,
        survey_id=survey_id,
        user_id=user.id,
        display_name=user.display_name,
    )
    # Tell the client what its connection id is so it can ignore its
    # own focus.update broadcasts.
    try:
        await websocket.send_json(
            {
                "type": "auth.ok",
                "connection_id": collab.connection_id,
                "color": collab.color,
            }
        )
    except Exception:
        await manager.disconnect(survey_id, collab.connection_id)
        return

    reaper_task = asyncio.create_task(_focus_reaper(survey_id))

    # ── Step 2: message loop ────────────────────────────────────────
    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue
            msg_type = message.get("type")

            if msg_type == "focus.acquire":
                question_id = message.get("question_id")
                if question_id is not None and not isinstance(question_id, str):
                    continue
                await manager.acquire_focus(
                    survey_id, collab.connection_id, question_id
                )
            elif msg_type == "focus.release":
                await manager.acquire_focus(
                    survey_id, collab.connection_id, None
                )
            elif msg_type == "heartbeat":
                await manager.heartbeat(survey_id, collab.connection_id)
                # Acknowledge so client can detect dead connections.
                try:
                    await websocket.send_json({"type": "heartbeat.ack"})
                except Exception:
                    break
            elif msg_type == "ping":
                # Lightweight liveness probe.
                try:
                    await websocket.send_json({"type": "pong"})
                except Exception:
                    break
            else:
                # Unknown frames are ignored to allow forward compat.
                logger.debug(
                    "ws_unknown_msg survey=%s type=%r", survey_id, msg_type
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 — log and clean up
        logger.warning(
            "ws_loop_error survey=%s conn=%s err=%s",
            survey_id,
            collab.connection_id,
            exc,
        )
    finally:
        reaper_task.cancel()
        try:
            await reaper_task
        except (asyncio.CancelledError, Exception):
            pass
        await manager.disconnect(survey_id, collab.connection_id)


async def _focus_reaper(survey_id: str) -> None:
    """Periodically sweep expired focus locks for a room."""
    while True:
        await asyncio.sleep(FOCUS_REAP_INTERVAL_SECONDS)
        try:
            await manager.reap_expired_focus(survey_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("focus_reap_error survey=%s err=%s", survey_id, exc)
