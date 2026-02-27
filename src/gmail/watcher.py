"""
ECUCONDOR - Gmail Watcher para depósitos Produbanco
Monitorea emails de bancaenlinea@produbanco.com para detectar transferencias recibidas.
"""

import base64
import json
import logging
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# Subjects que indican un depósito recibido (NO enviado)
DEPOSIT_QUERIES = [
    'from:bancaenlinea@produbanco.com subject:"Transferencia Recibida" is:unread',
    'from:bancaenlinea@produbanco.com subject:"Transferencia acreditada" is:unread',
    'from:bancaenlinea@produbanco.com subject:"Notificación Transferencia Acreditada" is:unread',
]


class GmailWatcher:
    """Monitorea Gmail para detectar depósitos Produbanco."""

    def __init__(self, token_path: str):
        self.token_path = token_path
        self._service = None

    def _get_service(self):
        """Obtiene o crea el servicio Gmail API con auto-refresh del token."""
        if self._service is not None:
            return self._service

        with open(self.token_path) as f:
            token_data = json.load(f)

        creds = Credentials(
            token=token_data.get("access_token"),
            refresh_token=token_data["refresh_token"],
            token_uri=token_data["token_uri"],
            client_id=token_data["client_id"],
            client_secret=token_data["client_secret"],
            scopes=["https://www.googleapis.com/auth/gmail.modify"],
        )

        self._service = build("gmail", "v1", credentials=creds)

        # Guardar token actualizado si se refrescó
        if creds.token != token_data.get("access_token"):
            token_data["access_token"] = creds.token
            if creds.expiry:
                token_data["expiry"] = creds.expiry.isoformat() + "Z"
            with open(self.token_path, "w") as f:
                json.dump(token_data, f, indent=2)
            logger.info("Token OAuth refrescado y guardado")

        return self._service

    def buscar_depositos_nuevos(self) -> list[dict]:
        """
        Busca emails no leídos de Produbanco que sean transferencias recibidas.

        Returns:
            Lista de dicts con: message_id, subject, html_body
        """
        service = self._get_service()
        resultados = []
        message_ids_vistos = set()

        for query in DEPOSIT_QUERIES:
            try:
                response = (
                    service.users()
                    .messages()
                    .list(userId="me", q=query, maxResults=20)
                    .execute()
                )

                messages = response.get("messages", [])
                for msg_ref in messages:
                    msg_id = msg_ref["id"]
                    if msg_id in message_ids_vistos:
                        continue
                    message_ids_vistos.add(msg_id)

                    # Obtener mensaje completo
                    msg = (
                        service.users()
                        .messages()
                        .get(userId="me", id=msg_id, format="full")
                        .execute()
                    )

                    # Extraer subject
                    subject = ""
                    for header in msg["payload"].get("headers", []):
                        if header["name"].lower() == "subject":
                            subject = header["value"]
                            break

                    # Filtrar transferencias ENVIADAS (no son depósitos)
                    subject_lower = subject.lower()
                    if "enviada por" in subject_lower and "recibida" not in subject_lower:
                        continue

                    # Extraer body HTML
                    html_body = self._extract_html_body(msg["payload"])
                    if not html_body:
                        logger.warning(
                            "Email sin body HTML", extra={"message_id": msg_id}
                        )
                        continue

                    resultados.append(
                        {
                            "message_id": msg_id,
                            "subject": subject,
                            "html_body": html_body,
                        }
                    )

            except Exception as e:
                logger.error(
                    "Error buscando emails: %s (query: %s)", str(e), query
                )

        logger.info("Encontrados %d depósitos nuevos", len(resultados))
        return resultados

    def marcar_procesado(self, message_id: str) -> None:
        """Quita el label UNREAD de un mensaje para no reprocesarlo."""
        service = self._get_service()
        try:
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            logger.info("Email marcado como leído: %s", message_id)
        except Exception as e:
            logger.error(
                "Error marcando email como leído: %s - %s", message_id, str(e)
            )

    def _extract_html_body(self, payload: dict) -> str | None:
        """Extrae el body HTML de un payload de Gmail API."""
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        if "parts" in payload:
            for part in payload["parts"]:
                result = self._extract_html_body(part)
                if result:
                    return result

        # Fallback: si el body está directamente en el payload
        if mime_type.startswith("text/") or mime_type == "":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        return None
