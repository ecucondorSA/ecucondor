"""
ECUCONDOR - Firmador XAdES-BES para SRI Ecuador
Wrapper sobre la implementación de referencia xades_bes_sri_ec
"""

import os
import tempfile
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class CertificateError(Exception):
    """Error relacionado con el certificado digital."""
    pass


class SigningError(Exception):
    """Error durante el proceso de firma."""
    pass


def sign_xml_sri(xml_string: str, cert_path: str, cert_password: str) -> str:
    """
    Firma un documento XML con XAdES-BES compatible con SRI Ecuador.

    Args:
        xml_string: XML sin firmar
        cert_path: Ruta al certificado .p12
        cert_password: Contraseña del certificado

    Returns:
        XML firmado

    Raises:
        SigningError: Si ocurre un error durante la firma
    """
    # Usar el nuevo firmador 2025 que replica exactamente el formato del SRI
    from src.sri.firmador_sri_2025 import FirmadorSRI2025

    try:
        firmador = FirmadorSRI2025(cert_path, cert_password)
        xml_firmado = firmador.firmar(xml_string)

        logger.info("Documento firmado exitosamente con XAdES-BES (SHA-256)")
        return xml_firmado

    except Exception as e:
        logger.error("Error al firmar documento", error=str(e))
        raise SigningError(f"Error al firmar documento: {e}") from e


class XAdESSigner:
    """
    Firmador de documentos XML con estándar XAdES-BES.

    Wrapper sobre la implementación de referencia para SRI Ecuador.
    """

    def __init__(self, cert_path: str | Path, cert_password: str) -> None:
        """
        Inicializa el firmador con un certificado .p12.

        Args:
            cert_path: Ruta al archivo .p12
            cert_password: Contraseña del certificado
        """
        self.cert_path = str(cert_path)
        self.cert_password = cert_password

        # Verificar que el certificado existe
        if not Path(self.cert_path).exists():
            raise CertificateError(f"Archivo de certificado no encontrado: {self.cert_path}")

        # Cargar info del certificado para validación
        self._load_certificate_info()

    def _load_certificate_info(self) -> None:
        """Carga información del certificado."""
        from cryptography.hazmat.primitives.serialization import pkcs12
        from datetime import datetime

        try:
            with open(self.cert_path, 'rb') as f:
                p12_data = f.read()

            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                p12_data,
                self.cert_password.encode('utf-8')
            )

            if certificate is None:
                raise CertificateError("No se encontró certificado en el archivo .p12")

            self._certificate = certificate

            # Extraer información
            subject_parts = []
            for attr in certificate.subject:
                subject_parts.append(f"{attr.oid._name}={attr.value}")

            self._cert_info = {
                "subject": ", ".join(subject_parts),
                "not_before": certificate.not_valid_before_utc.isoformat(),
                "not_after": certificate.not_valid_after_utc.isoformat(),
            }

            logger.info(
                "Certificado cargado exitosamente",
                subject=self._cert_info.get("subject"),
                valid_until=self._cert_info.get("not_after"),
            )

        except Exception as e:
            logger.error("Error al cargar certificado", error=str(e))
            raise CertificateError(f"Error al cargar certificado: {e}") from e

    def sign(self, xml_string: str) -> str:
        """
        Firma un documento XML con XAdES-BES.

        Args:
            xml_string: Documento XML sin firmar

        Returns:
            Documento XML firmado
        """
        return sign_xml_sri(xml_string, self.cert_path, self.cert_password)

    @property
    def certificate_info(self) -> dict:
        """Retorna información del certificado cargado."""
        return self._cert_info.copy()

    def is_certificate_valid(self) -> bool:
        """Verifica si el certificado está vigente."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        not_before = self._certificate.not_valid_before_utc
        not_after = self._certificate.not_valid_after_utc
        return not_before <= now <= not_after
