"""Messaggi d'errore leggibili (tradotti) per i comandi."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError

from .api import AldesBoxNotConnectedError, AldesBridgeConnectionError, AldesBridgeError
from .const import DOMAIN


def command_error(err: AldesBridgeError) -> HomeAssistantError:
    """Traduce un errore del bridge. Il comando resta rifiutato: nessuna coda."""
    if isinstance(err, AldesBoxNotConnectedError):
        return HomeAssistantError(translation_domain=DOMAIN, translation_key="box_not_connected")
    if isinstance(err, AldesBridgeConnectionError):
        return HomeAssistantError(translation_domain=DOMAIN, translation_key="bridge_unreachable")
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="command_rejected",
        translation_placeholders={"detail": str(err)},
    )
