"""Real-drone flight-command relay (WebSocket).

Reverse direction of the telemetry pipeline — commands travel
browser -> server -> desktop -> drone:

    SPA useDroneCommands (Real Drone -> Livestream Host, Takeoff/Landing)
      -> WS /api/drone/command             (this module, browser side)
        -> WS /api/drone/command/downlink  (this module, relay side)
          -> extension/crazyflie_bridge/telemetry_relay.py command_forwarder()
            -> motion_control_ws.py (owns the Crazyflie link, ws://:8765)

Kept deliberately separate from telemetry.py: commands are validated against
a strict whitelist (action + numeric clamps mirroring
motion_control_ws._handle_command) before they are forwarded — the server
never relays arbitrary payloads to the drone.

Downlink auth: same shared secret as telemetry publish
(config.json -> "drone" -> "telemetry_token", passed as ?token=...).

Acks: every browser command gets an immediate {"type": "ack", ...} frame so
the UI can tell apart "delivered towards the drone" from "no drone link".
The ack means the command was forwarded to the desktop relay; the bridge
itself may still refuse it (e.g. the USB-cable takeoff interlock).
"""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .config import CONFIG

logger = logging.getLogger(__name__)

router = APIRouter(tags=["drone-commands"])

_downlink: WebSocket | None = None    # the ONE desktop relay connection
_commander: WebSocket | None = None   # the ONE browser connection (new replaces old)
_LOCK = asyncio.Lock()


def _token() -> str:
    return CONFIG.get("drone", {}).get("telemetry_token", "") or ""


def _clamp(value, lo, hi, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _validate(raw: dict) -> dict | None:
    """Whitelist + clamp an incoming command; None = reject.

    Mirrors the accepted schema and clamps of motion_control_ws._dispatch_command
    (note: the bridge spells the yaw field "yawrate").
    """
    if not isinstance(raw, dict):
        return None
    action = raw.get("action")
    if action == "takeoff":
        return {"action": "takeoff", "height": _clamp(raw.get("height", 0.5), 0.1, 1.5, 0.5)}
    if action in ("land", "stop", "estop"):
        return {"action": action}
    if action == "move":
        return {
            "action": "move",
            "vx": _clamp(raw.get("vx", 0.0), -0.5, 0.5, 0.0),
            "vy": _clamp(raw.get("vy", 0.0), -0.5, 0.5, 0.0),
            "vz": _clamp(raw.get("vz", 0.0), -0.5, 0.5, 0.0),
            "yawrate": _clamp(raw.get("yawrate", 0.0), -120.0, 120.0, 0.0),
        }
    if action in ("up", "down", "forward", "back", "left", "right"):
        return {"action": action, "distance": _clamp(raw.get("distance", 0.2), 0.05, 1.0, 0.2)}
    return None


async def _ack(ws: WebSocket, action: str, delivered: bool, reason: str = "") -> None:
    frame = {"type": "ack", "action": action, "delivered": delivered}
    if reason:
        frame["reason"] = reason
    try:
        await ws.send_text(json.dumps(frame))
    except Exception:
        pass


@router.websocket("/drone/command/downlink")
async def command_downlink(websocket: WebSocket) -> None:
    """The desktop relay connects here to receive commands (token-guarded)."""
    global _downlink
    token = _token()
    if token and websocket.query_params.get("token", "") != token:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    async with _LOCK:
        if _downlink is not None:
            try:
                await _downlink.close(code=4000)  # replaced by the newer relay
            except Exception:
                pass
        _downlink = websocket
    logger.info("drone command downlink connected: %s", websocket.client)
    try:
        while True:
            await websocket.receive_text()  # hold open; nothing expected inbound
    except WebSocketDisconnect:
        pass
    finally:
        async with _LOCK:
            if _downlink is websocket:
                _downlink = None
        logger.info("drone command downlink disconnected")


@router.websocket("/drone/command")
async def command(websocket: WebSocket) -> None:
    """Browser command channel: validate, forward to the downlink, ack."""
    global _commander
    await websocket.accept()
    async with _LOCK:
        if _commander is not None:
            try:
                await _commander.close(code=4000)  # single commander: newest wins
            except Exception:
                pass
        _commander = websocket
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await _ack(websocket, "", False, "invalid json")
                continue
            cmd = _validate(payload)
            if cmd is None:
                await _ack(websocket, str(payload.get("action", "")), False, "unknown action")
                continue
            downlink = _downlink
            if downlink is None:
                await _ack(websocket, cmd["action"], False, "no drone link")
                continue
            try:
                await downlink.send_text(json.dumps(cmd))
                logger.info("drone command forwarded: %s (from %s)", cmd, websocket.client)
                await _ack(websocket, cmd["action"], True)
            except Exception as e:  # downlink died mid-send
                logger.warning("drone command forward failed: %s", e)
                await _ack(websocket, cmd["action"], False, "downlink send failed")
    except WebSocketDisconnect:
        pass
    finally:
        async with _LOCK:
            if _commander is websocket:
                _commander = None
