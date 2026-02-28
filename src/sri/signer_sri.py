"""
ECUCONDOR - Firmador XAdES-BES para SRI Ecuador
Implementación unificada SHA-256 compatible con SRI 2025+.

Replica exactamente la estructura del facturador oficial del SRI.
"""

import base64
import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

import structlog

logger = structlog.get_logger(__name__)


# ===== Excepciones =====

class CertificateError(Exception):
    """Error relacionado con el certificado digital."""
    pass


class SigningError(Exception):
    """Error durante el proceso de firma."""
    pass


# ===== Constantes =====

NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"
NS_XADES141 = "http://uri.etsi.org/01903/v1.4.1#"

# Algoritmos SHA-256 (requeridos por SRI 2025)
ALG_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ALG_SIGNATURE = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
ALG_DIGEST = "http://www.w3.org/2001/04/xmlenc#sha256"
ALG_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"


def _sha256_digest(data: bytes) -> str:
    """Calcula SHA-256 y retorna en Base64."""
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def _c14n(element: etree._Element) -> bytes:
    """Canonicaliza un elemento XML usando C14N inclusivo."""
    return etree.tostring(element, method="c14n", exclusive=False, with_comments=False)


# ===== Clase Principal =====

class XAdESSigner:
    """
    Firmador de documentos XML con estándar XAdES-BES.

    Implementación SHA-256 compatible con SRI Ecuador 2025+.
    Replica exactamente la estructura del facturador oficial.
    """

    def __init__(self, cert_path: str | Path, cert_password: str) -> None:
        """
        Inicializa el firmador con un certificado .p12.

        Args:
            cert_path: Ruta al archivo .p12
            cert_password: Contraseña del certificado

        Raises:
            CertificateError: Si no se puede cargar el certificado
        """
        self.cert_path = str(cert_path)
        self.cert_password = cert_password

        if not Path(self.cert_path).exists():
            raise CertificateError(f"Archivo de certificado no encontrado: {self.cert_path}")

        self._load_certificate()

    def _load_certificate(self) -> None:
        """Carga el certificado y la clave privada desde el archivo .p12."""
        try:
            with open(self.cert_path, "rb") as f:
                p12_data = f.read()

            private_key, certificate, _ = pkcs12.load_key_and_certificates(
                p12_data,
                self.cert_password.encode("utf-8"),
            )

            if private_key is None:
                raise CertificateError("No se encontró la clave privada en el certificado")
            if certificate is None:
                raise CertificateError("No se encontró certificado en el archivo .p12")

            self._private_key = private_key
            self._certificate: x509.Certificate = certificate

            # Certificado en DER y Base64
            self._cert_der = certificate.public_bytes(serialization.Encoding.DER)
            self._cert_b64 = base64.b64encode(self._cert_der).decode("ascii")

            # Datos del emisor
            self._issuer_name = self._format_issuer()
            self._serial_number = str(certificate.serial_number)

            # Info para logs y validación
            subject_parts = [f"{attr.oid._name}={attr.value}" for attr in certificate.subject]
            self._cert_info = {
                "subject": ", ".join(subject_parts),
                "issuer": self._issuer_name,
                "serial_number": self._serial_number,
                "not_before": certificate.not_valid_before_utc.isoformat(),
                "not_after": certificate.not_valid_after_utc.isoformat(),
            }

            logger.info(
                "Certificado cargado exitosamente",
                subject=self._cert_info["subject"],
                valid_until=self._cert_info["not_after"],
            )

        except CertificateError:
            raise
        except Exception as e:
            logger.error("Error al cargar certificado", error=str(e))
            raise CertificateError(f"Error al cargar certificado: {e}") from e

    def _format_issuer(self) -> str:
        """Formatea el issuer en el orden que espera el SRI (CN,OU,O,C)."""
        partes = {}
        for attr in self._certificate.issuer:
            oid_name = attr.oid._name
            if oid_name == "commonName":
                partes["CN"] = attr.value
            elif oid_name == "organizationalUnitName":
                partes["OU"] = attr.value
            elif oid_name == "organizationName":
                partes["O"] = attr.value
            elif oid_name == "countryName":
                partes["C"] = attr.value

        return ",".join(f"{k}={partes[k]}" for k in ["CN", "OU", "O", "C"] if k in partes)

    def sign(self, xml_string: str) -> str:
        """
        Firma un documento XML con XAdES-BES.

        Args:
            xml_string: Documento XML sin firmar

        Returns:
            Documento XML firmado

        Raises:
            SigningError: Si ocurre un error durante la firma
        """
        try:
            parser = etree.XMLParser(remove_blank_text=True)
            root = etree.fromstring(xml_string.encode("utf-8"), parser)

            sig_id = f"xmldsig-{uuid.uuid4()}"
            signature = self._build_signature(root, sig_id)
            root.append(signature)

            xml_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
            logger.info("Documento firmado exitosamente con XAdES-BES (SHA-256)")
            return xml_bytes.decode("utf-8")

        except Exception as e:
            logger.error("Error al firmar documento", error=str(e))
            raise SigningError(f"Error al firmar documento: {e}") from e

    def _build_signature(self, root: etree._Element, sig_id: str) -> etree._Element:
        """Crea el elemento ds:Signature completo."""

        signature = etree.Element(
            f"{{{NS_DS}}}Signature",
            nsmap={"ds": NS_DS},
            Id=sig_id,
        )

        # --- SignedInfo ---
        signed_info = etree.SubElement(signature, f"{{{NS_DS}}}SignedInfo")
        etree.SubElement(signed_info, f"{{{NS_DS}}}CanonicalizationMethod", Algorithm=ALG_C14N)
        etree.SubElement(signed_info, f"{{{NS_DS}}}SignatureMethod", Algorithm=ALG_SIGNATURE)

        # Reference 1: Comprobante
        ref_comprobante = etree.SubElement(
            signed_info,
            f"{{{NS_DS}}}Reference",
            Id=f"{sig_id}-ref0",
            URI="#comprobante",
        )
        transforms = etree.SubElement(ref_comprobante, f"{{{NS_DS}}}Transforms")
        etree.SubElement(transforms, f"{{{NS_DS}}}Transform", Algorithm=ALG_ENVELOPED)
        etree.SubElement(ref_comprobante, f"{{{NS_DS}}}DigestMethod", Algorithm=ALG_DIGEST)
        etree.SubElement(ref_comprobante, f"{{{NS_DS}}}DigestValue").text = _sha256_digest(
            _c14n(root)
        )

        # Reference 2: SignedProperties (digest se calcula después)
        signed_props_id = f"{sig_id}-signedprops"
        ref_props = etree.SubElement(
            signed_info,
            f"{{{NS_DS}}}Reference",
            Type="http://uri.etsi.org/01903#SignedProperties",
            URI=f"#{signed_props_id}",
        )
        etree.SubElement(ref_props, f"{{{NS_DS}}}DigestMethod", Algorithm=ALG_DIGEST)
        digest_props_elem = etree.SubElement(ref_props, f"{{{NS_DS}}}DigestValue")

        # --- KeyInfo ---
        key_info = etree.SubElement(signature, f"{{{NS_DS}}}KeyInfo")
        x509_data = etree.SubElement(key_info, f"{{{NS_DS}}}X509Data")
        etree.SubElement(x509_data, f"{{{NS_DS}}}X509Certificate").text = self._cert_b64

        # --- Object (XAdES) ---
        obj = etree.SubElement(signature, f"{{{NS_DS}}}Object")
        qualifying_props = etree.SubElement(
            obj,
            f"{{{NS_XADES}}}QualifyingProperties",
            nsmap={"xades": NS_XADES, "xades141": NS_XADES141},
            Target=f"#{sig_id}",
        )

        signed_props = etree.SubElement(
            qualifying_props,
            f"{{{NS_XADES}}}SignedProperties",
            Id=signed_props_id,
        )

        # SignedSignatureProperties
        signed_sig_props = etree.SubElement(signed_props, f"{{{NS_XADES}}}SignedSignatureProperties")

        # SigningTime (zona horaria Ecuador -05:00)
        ecuador_tz = timezone(timedelta(hours=-5))
        signing_time = datetime.now(ecuador_tz).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "-05:00"
        etree.SubElement(signed_sig_props, f"{{{NS_XADES}}}SigningTime").text = signing_time

        # SigningCertificate
        signing_cert = etree.SubElement(signed_sig_props, f"{{{NS_XADES}}}SigningCertificate")
        cert_elem = etree.SubElement(signing_cert, f"{{{NS_XADES}}}Cert")

        cert_digest = etree.SubElement(cert_elem, f"{{{NS_XADES}}}CertDigest")
        etree.SubElement(cert_digest, f"{{{NS_DS}}}DigestMethod", Algorithm=ALG_DIGEST)
        etree.SubElement(cert_digest, f"{{{NS_DS}}}DigestValue").text = _sha256_digest(
            self._cert_der
        )

        issuer_serial = etree.SubElement(cert_elem, f"{{{NS_XADES}}}IssuerSerial")
        etree.SubElement(issuer_serial, f"{{{NS_DS}}}X509IssuerName").text = self._issuer_name
        etree.SubElement(issuer_serial, f"{{{NS_DS}}}X509SerialNumber").text = self._serial_number

        # SignedDataObjectProperties
        signed_data_props = etree.SubElement(
            signed_props, f"{{{NS_XADES}}}SignedDataObjectProperties"
        )
        data_obj_format = etree.SubElement(
            signed_data_props,
            f"{{{NS_XADES}}}DataObjectFormat",
            ObjectReference=f"#{sig_id}-ref0",
        )
        etree.SubElement(data_obj_format, f"{{{NS_XADES}}}Description").text = "FIRMA DIGITAL SRI"
        etree.SubElement(data_obj_format, f"{{{NS_XADES}}}MimeType").text = "text/xml"
        etree.SubElement(data_obj_format, f"{{{NS_XADES}}}Encoding").text = "UTF-8"

        # Calcular hash de SignedProperties
        digest_props_elem.text = _sha256_digest(_c14n(signed_props))

        # --- SignatureValue ---
        signed_info_bytes = _c14n(signed_info)
        signature_value = self._private_key.sign(
            signed_info_bytes,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

        sig_value = etree.Element(
            f"{{{NS_DS}}}SignatureValue", Id=f"{sig_id}-sigvalue"
        )
        sig_value.text = base64.b64encode(signature_value).decode("ascii")
        signature.insert(1, sig_value)

        return signature

    @property
    def certificate_info(self) -> dict[str, Any]:
        """Retorna información del certificado cargado."""
        return self._cert_info.copy()

    def is_certificate_valid(self) -> bool:
        """Verifica si el certificado está vigente."""
        now = datetime.now(timezone.utc)
        not_before = self._certificate.not_valid_before_utc
        not_after = self._certificate.not_valid_after_utc
        return not_before <= now <= not_after


def sign_xml_sri(xml_string: str, cert_path: str, cert_password: str) -> str:
    """
    Función de conveniencia para firmar un XML.

    Args:
        xml_string: XML sin firmar
        cert_path: Ruta al certificado .p12
        cert_password: Contraseña del certificado

    Returns:
        XML firmado

    Raises:
        SigningError: Si ocurre un error durante la firma
    """
    signer = XAdESSigner(cert_path, cert_password)
    return signer.sign(xml_string)
