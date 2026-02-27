"""
ECUCONDOR - Notificaciones por Telegram
Envía alertas al chat configurado. Si no hay token, solo loguea.
"""

import logging

import requests

logger = logging.getLogger(__name__)


def enviar_alerta(mensaje: str, token: str = "", chat_id: str = "") -> bool:
    """
    Envía un mensaje de alerta por Telegram.

    Args:
        mensaje: Texto del mensaje a enviar
        token: Bot token de Telegram (si vacío, solo loguea)
        chat_id: Chat ID destino

    Returns:
        True si se envió correctamente, False si falló o no configurado
    """
    if not token or not chat_id:
        logger.info("[ALERTA] %s", mensaje)
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": f"ECUCONDOR\n\n{mensaje}",
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        logger.warning("Telegram respondió %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.warning("Error enviando Telegram: %s", str(e))
        return False
