"""Client HTTP per l'API dell'app Aldes Bridge (progetto di saniho, licenza MIT).

Nessun codice del bridge e' usato: si interrogano solo le sue API HTTP.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class AldesBridgeError(Exception):
    """Errore generico del bridge."""


class AldesBridgeConnectionError(AldesBridgeError):
    """Bridge non raggiungibile."""


class AldesBridgeResponseError(AldesBridgeError):
    """Risposta del bridge non valida."""


class AldesBoxNotConnectedError(AldesBridgeResponseError):
    """Il bridge rifiuta il comando perche' la Box non e' collegata (non viene messo in coda)."""


class CommandSuperseded(Exception):
    """Un comando automatico e' stato scavalcato da uno piu' recente mentre aspettava la pausa minima."""


def _is_box_not_connected(text: Any) -> bool:
    return "aucune box" in str(text).lower()


@dataclass
class BridgeState:
    """Ultimo payload noto inviato dalla Box."""

    payload: dict[str, Any]
    timestamp: float  # epoch del dato


def _looks_valid(payload: Any) -> bool:
    return isinstance(payload, dict) and "current_mode" in payload


def _parse_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw if _looks_valid(raw) else None
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if _looks_valid(data) else None
    return None


class AldesBridgeClient:
    """Client del bridge."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int) -> None:
        self._session = session
        self.host = host
        self.port = port
        self._base = f"http://{host}:{port}"

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> Any:
        try:
            async with self._session.request(
                method, f"{self._base}{path}", timeout=REQUEST_TIMEOUT, **kwargs
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    if _is_box_not_connected(body):
                        raise AldesBoxNotConnectedError(body[:200])
                    raise AldesBridgeResponseError(f"HTTP {resp.status} su {path}")
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise AldesBridgeConnectionError(str(err) or type(err).__name__) from err
        except ValueError as err:
            raise AldesBridgeResponseError(f"JSON non valido da {path}") from err

    async def get_health(self) -> dict[str, Any]:
        data = await self._request("GET", "/api/health")
        if not isinstance(data, dict):
            raise AldesBridgeResponseError("health non valido")
        return data

    async def get_config(self) -> dict[str, Any]:
        data = await self._request("GET", "/api/config")
        if not isinstance(data, dict) or "client_id" not in data:
            raise AldesBridgeResponseError("config non valida")
        return data

    async def get_latest_state(self) -> BridgeState | None:
        """Ultimo payload completo: prima dallo storico persistente, poi dal registro."""
        state = await self._state_from_history()
        if state is None:
            state = await self._state_from_logs()
        return state

    async def _state_from_history(self) -> BridgeState | None:
        data = await self._request(
            "GET", "/api/history/search", params={"text": "current_mode", "limit": 10}
        )
        best: BridgeState | None = None
        for msg in (data or {}).get("messages", []):
            payload = _parse_payload(msg.get("payload"))
            if payload is None or "outside_tpt" not in payload:
                continue
            ts = payload.get("_upd_at") or msg.get("ts") or 0
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                continue
            if best is None or ts > best.timestamp:
                best = BridgeState(payload, ts)
        return best

    async def get_ff_history(
        self, page_size: int, max_pages: int
    ) -> list[tuple[float, float]]:
        """Serie (timestamp, ff_cpt) dallo storico, dal piu' recente al meno recente."""
        rows: dict[float, float] = {}
        offset = 0
        for _ in range(max_pages):
            data = await self._request(
                "GET",
                "/api/history/search",
                params={"text": "current_mode", "limit": page_size, "offset": offset},
            )
            messages = (data or {}).get("messages", [])
            if not messages:
                break
            for msg in messages:
                payload = _parse_payload(msg.get("payload"))
                if payload is None or "outside_tpt" not in payload:
                    continue
                ff = payload.get("ff_cpt")
                ts = payload.get("_upd_at") or msg.get("ts")
                if not isinstance(ff, (int, float)) or ts is None:
                    continue
                rows[round(float(ts), 0)] = float(ff)
            offset += len(messages)
            if offset >= int((data or {}).get("total", 0)):
                break
        return sorted(rows.items(), reverse=True)

    async def _state_from_logs(self) -> BridgeState | None:
        data = await self._request("GET", "/api/logs", params={"limit": 50})
        best: BridgeState | None = None
        for ev in (data or {}).get("events", []):
            payload = _parse_payload(ev.get("payload"))
            if payload is None or "outside_tpt" not in payload:
                continue
            ts = payload.get("_upd_at")
            if ts is None:
                try:
                    ts = datetime.fromisoformat(ev["ts"]).timestamp()
                except (KeyError, ValueError, TypeError):
                    continue
            ts = float(ts)
            if best is None or ts > best.timestamp:
                best = BridgeState(payload, ts)
        return best

    async def send_command(
        self, client_id: str, method: str, params: list[Any]
    ) -> None:
        """Invia un comando alla Box tramite il bridge (QoS 1)."""
        body = {
            "topic": f"devices/{client_id}/messages/devicebound",
            "payload": json.dumps(
                {"id": 1, "jsonrpc": "2.0", "method": method, "params": params},
                separators=(",", ":"),
            ),
            "qos": 1,
        }
        data = await self._request("POST", "/api/send", json=body)
        if not isinstance(data, dict) or not data.get("ok"):
            if _is_box_not_connected(data):
                raise AldesBoxNotConnectedError(str(data)[:200])
            raise AldesBridgeResponseError(f"Comando rifiutato dal bridge: {data}")
