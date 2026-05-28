"""
Background QUIC session management.

- Runs a QUIC accept loop in a background asyncio thread so the agent can
  receive inbound P2P/relay messages from other GANN agents.
- Keeps inbound sessions alive in ``state.pending_sessions`` so Claude can
  reply via ``gann_reply``.  Sessions that go unreplied are cleaned up after
  a configurable timeout (default 5 minutes).
- Provides ``send_message`` which dials a peer over QUIC (direct-first,
  relay fallback), sends a JSON payload, and returns the response.
- Provides ``reply_to_session`` which sends a response through a pending
  inbound session and then closes it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from .state import GannState, PendingSession

logger = logging.getLogger("gann.quic")

# How long to keep an unreplied inbound session before auto-closing (seconds)
PENDING_SESSION_TTL = 300.0


# ---------------------------------------------------------------------------
# Inbound: QUIC responder loop
# ---------------------------------------------------------------------------

async def _handle_inbound_session(
    state: GannState,
    channel: Any,
    result: Any,
) -> None:
    """Read one inbound payload, hold the session open for Claude to reply."""
    try:
        payload: dict = {}
        writer: Any = None

        if result.mode == "relay" and result.relay_transport and result.token:
            frame = await result.relay_transport.recv_relay_data()
            raw = frame.payload
            payload = json.loads(raw) if isinstance(raw, (str, bytes)) else raw

        elif result.mode == "direct" and result.peer_connection:
            reader, writer = await result.peer_connection.accept_bi()
            try:
                raw = await asyncio.wait_for(reader.read(), timeout=30.0)
            except asyncio.TimeoutError:
                raw = b""
            payload = json.loads(raw.decode()) if raw else {}
        else:
            logger.warning("inbound session with no usable transport")
            return

        session_id = str(result.session_id)
        peer_agent_id = str(getattr(result, "peer_agent_id", "") or "")

        # Store the open session so gann_reply can send the real response
        pending = PendingSession(
            session_id=session_id,
            peer_agent_id=peer_agent_id,
            mode=result.mode,
            channel=channel,
            result=result,
            writer=writer,
        )
        with state._pending_lock:
            state.pending_sessions[session_id] = pending

        # Push the message to the incoming queue for gann_receive_messages
        await state.incoming.put({
            "session_id": session_id,
            "peer_agent_id": peer_agent_id,
            "mode": result.mode,
            "payload": payload,
            "awaiting_reply": True,
        })

        logger.info(
            "inbound message queued, session %s held open for reply",
            session_id,
        )

    except Exception:
        logger.exception("error handling inbound QUIC session")
        # On error, signal disconnect and clean up immediately
        peer_id = str(getattr(result, "peer_agent_id", "") or "")
        try:
            channel.disconnect_session(
                str(result.session_id), peer_id, "error"
            )
        except Exception:
            pass
        await _close_session_resources(channel, result)


async def _close_session_resources(channel: Any, result: Any) -> None:
    """Close QUIC connection, relay transport, and signaling channel."""
    if getattr(result, "peer_connection", None):
        try:
            await result.peer_connection.close()
        except Exception:
            pass
    if getattr(result, "relay_transport", None):
        try:
            await result.relay_transport.close()
        except Exception:
            pass
    # Close the signaling WebSocket
    if channel is not None:
        try:
            channel.close()
        except Exception:
            pass


async def _cleanup_stale_sessions(state: GannState) -> None:
    """Periodically close sessions that Claude never replied to."""
    while state.connected:
        await asyncio.sleep(30.0)
        now = time.monotonic()
        stale: list[str] = []

        with state._pending_lock:
            for sid, ps in state.pending_sessions.items():
                if now - ps.created_at > PENDING_SESSION_TTL:
                    stale.append(sid)

        for sid in stale:
            logger.warning("closing stale pending session %s (no reply)", sid)
            await _close_pending_session(state, sid, timeout=True)


async def quic_accept_loop(state: GannState) -> None:
    """Long-running loop that accepts inbound QUIC offers from peers."""
    from gann_sdk.quic_session import QuicDirectFirstOptions

    logger.info("QUIC responder loop started")
    consecutive_errors = 0

    # Start the stale-session cleanup task
    asyncio.create_task(_cleanup_stale_sessions(state))

    while state.connected:
        try:
            # direct_timeout must match (or exceed) the initiator's setting so
            # cross-tenant pairs can complete a direct QUIC handshake instead of
            # falling back to relay (relays are tenant-scoped and cannot bridge
            # peers that hold different GANN_API_KEYs).
            channel, result = await state.client.accept_quic_direct_first(
                options=QuicDirectFirstOptions(direct_timeout=20.0),
                offer_timeout=300.0,
            )
            consecutive_errors = 0
            logger.info(
                "inbound session: mode=%s session=%s",
                result.mode,
                result.session_id,
            )
            asyncio.create_task(
                _handle_inbound_session(state, channel, result)
            )

        except asyncio.TimeoutError:
            consecutive_errors = 0

        except Exception:
            consecutive_errors += 1
            logger.exception("responder loop error (#%d)", consecutive_errors)
            if consecutive_errors >= 3:
                await asyncio.sleep(5.0)
                consecutive_errors = 0
            else:
                await asyncio.sleep(1.0)

        await asyncio.sleep(0.1)


def start_accept_loop(state: GannState) -> None:
    """Schedule the QUIC accept loop on the background event loop."""
    if state.loop is None:
        raise RuntimeError("event loop not started")
    asyncio.run_coroutine_threadsafe(quic_accept_loop(state), state.loop)


# ---------------------------------------------------------------------------
# Reply: send response through a pending inbound session
# ---------------------------------------------------------------------------

async def _close_pending_session(
    state: GannState,
    session_id: str,
    *,
    timeout: bool = False,
) -> None:
    """Remove a pending session and close its resources."""
    with state._pending_lock:
        ps = state.pending_sessions.pop(session_id, None)
    if ps is None:
        return

    result = ps.result
    channel = ps.channel

    # Disconnect signaling
    try:
        reason = "timeout" if timeout else "reply_sent"
        channel.disconnect_session(session_id, ps.peer_agent_id, reason)
    except Exception:
        pass

    await _close_session_resources(channel, result)


async def _reply_impl(
    state: GannState,
    session_id: str,
    response_payload: dict,
) -> dict:
    """Send a response through a held-open inbound session."""
    with state._pending_lock:
        ps = state.pending_sessions.get(session_id)

    if ps is None:
        return {
            "replied": False,
            "error": f"No pending session {session_id}. It may have timed out or already been replied to.",
        }

    result = ps.result
    try:
        encoded = json.dumps(response_payload, separators=(",", ":")).encode()

        if ps.mode == "relay" and result.relay_transport and result.token:
            await result.relay_transport.relay_send(
                result.token, result.session_id, response_payload
            )
        elif ps.mode == "direct" and ps.writer is not None:
            ps.writer.write(encoded)
            await ps.writer.drain()
            ps.writer.write_eof()
            await asyncio.sleep(0.1)
        else:
            return {"replied": False, "error": "no usable transport on pending session"}

        logger.info("reply sent on session %s (mode=%s)", session_id, ps.mode)
        return {
            "replied": True,
            "session_id": session_id,
            "peer_agent_id": ps.peer_agent_id,
            "mode": ps.mode,
        }

    except Exception as exc:
        logger.exception("failed to reply on session %s", session_id)
        return {"replied": False, "error": str(exc)}
    finally:
        await _close_pending_session(state, session_id)


def reply_to_session(
    state: GannState,
    session_id: str,
    response_payload: dict,
) -> dict:
    """Synchronously reply to a pending inbound session (blocks until sent)."""
    state.ensure_connected()
    if state.loop is None:
        raise RuntimeError("event loop not started")
    future = asyncio.run_coroutine_threadsafe(
        _reply_impl(state, session_id, response_payload), state.loop
    )
    return future.result(timeout=30.0)


# ---------------------------------------------------------------------------
# Outbound: dial a peer and send a message
# ---------------------------------------------------------------------------

async def _send_impl(state: GannState, peer_id: uuid.UUID, payload: dict) -> dict:
    from gann_sdk.quic_session import QuicDirectFirstOptions

    channel, result = await state.client.dial_quic_direct_first(
        peer_id,
        options=QuicDirectFirstOptions(direct_timeout=5.0),
    )

    # Soika-style runtime bridges (the standard GANN agent runtime) expect the
    # request envelope `{"event": "request", "payload": <user payload>}` and
    # respond with a stream of frames terminated by `message_end`/`stop`/`error`.
    # Any frame whose `event` is not "request" is dropped by the responder, so
    # without this wrapping the responder hangs and we time out at 60s/120s.
    request_envelope = {"event": "request", "payload": payload}
    encoded = json.dumps(request_envelope, separators=(",", ":")).encode()
    terminal_events = {"message_end", "stop", "error"}
    # Frames to silently drop (don't return them but do reset idle clock).
    skip_events = {"ready", "ping", "pong"}
    # Image/video generation can take minutes. We wait for the overall budget
    # and ONLY break early on a real terminal frame (message_end / stop /
    # error). The Soika responder bridge sends `ping` every ~5s as keepalive,
    # but if it stalls we still wait the full overall budget rather than
    # cutting off mid-generation.
    overall_timeout = 600.0

    def _decode_frame(raw: object) -> dict:
        if isinstance(raw, (str, bytes)):
            try:
                txt = raw.decode() if isinstance(raw, bytes) else raw
                return json.loads(txt)
            except Exception:
                return {"raw": raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace")}
        if isinstance(raw, dict):
            return raw
        return {"raw": str(raw)}

    try:
        if result.mode == "relay" and result.relay_transport and result.token:
            await result.relay_transport.relay_send(
                result.token, result.session_id, request_envelope
            )

            frames: list[dict] = []
            terminal: dict | None = None
            deadline = asyncio.get_event_loop().time() + overall_timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    frame = await asyncio.wait_for(
                        result.relay_transport.recv_relay_data(),
                        timeout=remaining,
                    )
                except asyncio.TimeoutError:
                    break
                evt = _decode_frame(getattr(frame, "payload", frame))
                evt_name = str(evt.get("event") or evt.get("type") or "").lower()
                logger.info(
                    "gann_send relay frame received: event=%s session=%s",
                    evt_name or "<unknown>",
                    result.session_id,
                )
                if evt_name in skip_events:
                    continue
                frames.append(evt)
                if evt_name in terminal_events:
                    terminal = evt
                    break

            try:
                channel.disconnect_session(
                    str(result.session_id), str(peer_id), "request_completed"
                )
            except Exception:
                pass

            return {
                "sent": True,
                "mode": "relay",
                "session_id": str(result.session_id),
                "frames": frames,
                "terminal": terminal,
                "completed": terminal is not None,
            }

        elif result.mode == "direct" and result.peer_connection:
            reader, writer = await result.peer_connection.open_bi()
            writer.write(encoded)
            await writer.drain()
            writer.write_eof()
            frames: list[dict] = []
            terminal: dict | None = None
            buffer = b""
            deadline = asyncio.get_event_loop().time() + overall_timeout
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    chunk = await asyncio.wait_for(reader.read(65536), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                if not chunk:
                    break
                buffer += chunk
                # Try to split on newlines; many SDKs frame JSON-per-line.
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer = rest
                    line = line.strip()
                    if not line:
                        continue
                    evt = _decode_frame(line)
                    evt_name = str(evt.get("event") or evt.get("type") or "").lower()
                    if evt_name in skip_events:
                        continue
                    frames.append(evt)
                    if evt_name in terminal_events:
                        terminal = evt
                        break
                if terminal is not None:
                    break
            if terminal is None and buffer.strip():
                evt = _decode_frame(buffer.strip())
                evt_name = str(evt.get("event") or evt.get("type") or "").lower()
                if evt_name not in skip_events:
                    frames.append(evt)
                    if evt_name in terminal_events:
                        terminal = evt

            try:
                channel.disconnect_session(
                    str(result.session_id), str(peer_id), "request_completed"
                )
            except Exception:
                pass

            return {
                "sent": True,
                "mode": "direct",
                "session_id": str(result.session_id),
                "frames": frames,
                "terminal": terminal,
                "completed": terminal is not None,
            }
        else:
            return {"sent": False, "error": "no usable QUIC transport"}

    finally:
        if getattr(result, "peer_connection", None):
            try:
                await result.peer_connection.close()
            except Exception:
                pass
        if getattr(result, "relay_transport", None):
            try:
                await result.relay_transport.close()
            except Exception:
                pass
        if channel:
            try:
                channel.close()
            except Exception:
                pass


def send_message(state: GannState, peer_id: uuid.UUID, payload: dict) -> dict:
    """Synchronously send a message to a peer via QUIC (blocks until response)."""
    state.ensure_connected()
    if state.loop is None:
        raise RuntimeError("event loop not started")
    future = asyncio.run_coroutine_threadsafe(
        _send_impl(state, peer_id, payload), state.loop
    )
    return future.result(timeout=620.0)
