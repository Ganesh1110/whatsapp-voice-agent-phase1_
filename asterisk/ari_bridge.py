"""Asterisk ARI Stasis application.

Bridges an inbound SIP call (Jio trunk) to the FastAPI voice pipeline via
ARI ``externalMedia``. Asterisk acts as the WebSocket *client* for media and
connects to FastAPI's ``/ari/stream`` endpoint, which runs STT → LLM → TTS.

Per-call topology::

    Caller (SIP/Jio) ──[mixing bridge]── externalMedia ──ws──► FastAPI /ari/stream
                                              ▲                                      │
                                              └───────── PCM audio ◄───────────────┘

Run:
    python asterisk/ari_bridge.py

Environment variables (mirror .env.example):
    ARI_HOST, ARI_PORT, ARI_APP, ARI_USER, ARI_PASSWORD
    FASTAPI_HOST, FASTAPI_PORT, FASTAPI_PATH
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.parse

import httpx
import websockets

logger = logging.getLogger("ari-bridge")

ARI_HOST = os.getenv("ARI_HOST", "localhost")
ARI_PORT = int(os.getenv("ARI_PORT", "8088"))
ARI_APP = os.getenv("ARI_APP", "voice-bridge")
ARI_USER = os.getenv("ARI_USER", "voice-bridge")
ARI_PASSWORD = os.getenv("ARI_PASSWORD", "bridge-secret")

FASTAPI_HOST = os.getenv("FASTAPI_HOST", "localhost")
FASTAPI_PORT = int(os.getenv("FASTAPI_PORT", "8000"))
FASTAPI_PATH = os.getenv("FASTAPI_PATH", "/ari/stream")

ARI_BASE = f"http://{ARI_HOST}:{ARI_PORT}/ari"
EVENTS_WS = (
    "ws://"
    + f"{ARI_HOST}:{ARI_PORT}/ari/events?"
    + urllib.parse.urlencode(
        {
            "app": ARI_APP,
            "api_key": f"{ARI_USER}:{ARI_PASSWORD}",
        }
    )
)

RECONNECT_DELAY = 5.0


class Call:
    """Tracks one bridged call: caller channel + externalMedia + bridge."""

    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id
        self.external_media_id: str | None = None
        self.bridge_id: str | None = None
        self.done = False


calls: dict[str, Call] = {}
calls_lock = asyncio.Lock()


async def _ari_request(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    url = f"{ARI_BASE}{path}"
    resp = await client.request(method, url, **kwargs)
    if resp.status_code >= 400:
        logger.error("ARI %s %s → %s %s", method, path, resp.status_code, resp.text)
        resp.raise_for_status()
    return resp


async def _create_external_media(client: httpx.AsyncClient) -> str:
    """Create an externalMedia channel that connects to FastAPI /ari/stream.

    externalMediaServer=false tells Asterisk to connect *to* FastAPI (FastAPI is
    the WebSocket server at /ari/stream).
    """
    data = {
        "externalMediaHost": FASTAPI_HOST,
        "externalMediaPort": str(FASTAPI_PORT),
        "externalMediaPath": FASTAPI_PATH,
        "externalMediaServer": "false",
        "endpoint": "fastapi-voice",
    }
    resp = await _ari_request(client, "POST", "/channels/externalMedia", data=data)
    channel_id = resp.json().get("id")
    logger.info("Created externalMedia channel: %s", channel_id)
    return channel_id


async def _create_bridge(client: httpx.AsyncClient, name: str) -> str:
    resp = await _ari_request(
        client, "POST", "/bridges", data={"type": "mixing", "name": name}
    )
    bridge_id = resp.json().get("id")
    logger.info("Created mixing bridge: %s", bridge_id)
    return bridge_id


async def _add_channel_to_bridge(client: httpx.AsyncClient, bridge_id: str, channel_id: str):
    await _ari_request(
        client,
        "POST",
        f"/bridges/{bridge_id}/addChannel",
        params={"channel": channel_id},
    )
    logger.info("Added channel %s to bridge %s", channel_id, bridge_id)


async def _hangup_channel(client: httpx.AsyncClient, channel_id: str | None):
    if not channel_id:
        return
    try:
        await _ari_request(client, "POST", f"/channels/{channel_id}/hangup")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise


async def _destroy_bridge(client: httpx.AsyncClient, bridge_id: str | None):
    if not bridge_id:
        return
    try:
        await _ari_request(client, "DELETE", f"/bridges/{bridge_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise


async def teardown_call(client: httpx.AsyncClient, call: Call):
    """Hangup externalMedia and destroy the bridge for a finished call."""
    await _hangup_channel(client, call.external_media_id)
    await _destroy_bridge(client, call.bridge_id)
    call.done = True


async def handle_stasis_start(client: httpx.AsyncClient, channel_id: str):
    """A caller entered the Stasis app: bridge it to FastAPI via externalMedia."""
    async with calls_lock:
        if channel_id in calls:
            return
        call = Call(channel_id)
        calls[channel_id] = call

    try:
        em_id = await _create_external_media(client)
        call.external_media_id = em_id

        bridge_id = await _create_bridge(client, f"voice-bridge-{channel_id[:8]}")
        call.bridge_id = bridge_id

        # Add both legs to the mixing bridge. externalMedia may not yet be
        # connected to FastAPI; Asterisk starts media flow once both legs are up.
        await _add_channel_to_bridge(client, bridge_id, channel_id)
        await _add_channel_to_bridge(client, bridge_id, em_id)
        logger.info("Bridged caller %s ↔ externalMedia %s (bridge %s)", channel_id, em_id, bridge_id)
    except Exception:
        logger.exception("Failed to bridge channel %s; cleaning up", channel_id)
        await teardown_call(client, call)
        async with calls_lock:
            calls.pop(channel_id, None)


async def handle_stasis_end(client: httpx.AsyncClient, channel_id: str):
    """Caller left the Stasis app (e.g. hung up): tear down the bridge."""
    async with calls_lock:
        call = calls.pop(channel_id, None)
    if call is None:
        return
    await teardown_call(client, call)
    logger.info("Tore down bridge for channel %s", channel_id)


async def process_event(client: httpx.AsyncClient, event: dict):
    event_type = event.get("type")
    channel = event.get("channel", {})
    channel_id = channel.get("id")
    if event_type == "StasisStart" and channel_id:
        asyncio.create_task(handle_stasis_start(client, channel_id))
    elif event_type == "StasisEnd" and channel_id:
        asyncio.create_task(handle_stasis_end(client, channel_id))


async def events_loop(client: httpx.AsyncClient):
    """Connect to ARI events WebSocket and dispatch StasisStart/StasisEnd."""
    backoff = RECONNECT_DELAY
    while True:
        try:
            logger.info("Connecting to ARI events: %s", EVENTS_WS)
            async with websockets.connect(
                EVENTS_WS, ping_interval=20, ping_timeout=20, close_timeout=10
            ) as ws:
                backoff = RECONNECT_DELAY
                logger.info("ARI events connected (app=%s)", ARI_APP)
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    await process_event(client, event)
        except asyncio.CancelledError:
            raise
        except (websockets.ConnectionClosed, OSError) as exc:
            logger.warning(
                "ARI events disconnected (%s); reconnecting in %.1fs", exc, backoff
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


async def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s [ari-bridge] %(message)s",
    )
    logger.info(
        "ARI bridge starting (app=%s, fastapi=%s:%s%s)",
        ARI_APP,
        FASTAPI_HOST,
        FASTAPI_PORT,
        FASTAPI_PATH,
    )
    async with httpx.AsyncClient(
        auth=httpx.BasicAuth(ARI_USER, ARI_PASSWORD), timeout=10.0
    ) as client:
        await events_loop(client)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("ARI bridge stopped")
