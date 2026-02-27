"""
ECUCONDOR - Firmador XAdES-BES para Comprobantes Electrónicos SRI
Implementa la firma digital según el estándar XAdES-BES requerido por el SRI Ecuador.
"""

import base64
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

import structlog

logger = structlog.get_logger(__name__)


# Namespaces XML para la firma
NAMESPACES = {
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "etsi": "http://uri.etsi.org/01903/v1.3.2#",
}


class CertificateError(Exception):
    """Error relacionado con el certificado digital."""
    pass


class SigningError(Exception):
    """Error durante el proceso de firma."""
    pass


class XAdESSigner:
    """
    Firmador de documentos XML con estándar XAdES-BES.

    Este firmador implementa el estándar requerido por el SRI de Ecuador
    para comprobantes electrónicos.
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
        self.cert_path = Path(cert_path)
        self._load_certificate(cert_password)

    def _load_certificate(self, password: str) -> None:
        """Carga el certificado y la clave privada desde el archivo .p12."""
        try:
            if not self.cert_path.exists():
                raise CertificateError(f"Archivo de certificado no encontrado: {self.cert_path}")

            with open(self.cert_path, "rb") as f:
                p12_data = f.read()

            # Cargar el PKCS12
            private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
                p12_data,
                password.encode("utf-8")
            )

            if private_key is None:
                raise CertificateError("No se encontró la clave privada en el certificado")

            if certificate is None:
                raise CertificateError("No se encontró el certificado en el archivo .p12")

            self._private_key: rsa.RSAPrivateKey = private_key  # type: ignore
            self._certificate: x509.Certificate = certificate
            self._additional_certs = additional_certs or []

            # Extraer información del certificado
            self._cert_info = self._extract_cert_info()

            logger.info(
                "Certificado cargado exitosamente",
                subject=self._cert_info.get("subject"),
                valid_until=self._cert_info.get("not_after"),
            )

        except Exception as e:
            logger.error("Error al cargar certificado", error=str(e))
            raise CertificateError(f"Error al cargar certificado: {e}") from e

    def _extract_cert_info(self) -> dict[str, Any]:
        """Extrae información del certificado."""
        cert = self._certificate

        # Obtener subject como string
        subject_parts = []
        for attr in cert.subject:
            subject_parts.append(f"{attr.oid._name}={attr.value}")
        subject = ", ".join(subject_parts)

        # Obtener issuer en formato RFC4514 (para X509IssuerName en XAdES)
        # El formato debe ser: CN=nombre,OU=unidad,O=org,C=pais (orden inverso, sin espacios)
        issuer_rfc4514 = self._format_dn_rfc4514(cert.issuer)

        # Obtener issuer legible para logs
        issuer_parts = []
        for attr in cert.issuer:
            issuer_parts.append(f"{attr.oid._name}={attr.value}")
        issuer = ", ".join(issuer_parts)

        return {
            "subject": subject,
            "issuer": issuer,
            "issuer_rfc4514": issuer_rfc4514,
            "serial_number": str(cert.serial_number),
            "not_before": cert.not_valid_before_utc.isoformat(),
            "not_after": cert.not_valid_after_utc.isoformat(),
        }

    def _format_dn_rfc4514(self, name: x509.Name) -> str:
        """Formatea un DN X.509 según RFC4514.

        El formato RFC4514 es: CN=valor,OU=valor,O=valor,C=valor
        Los atributos van en orden inverso (de más específico a más general).
        Los caracteres especiales deben ser escapados.
        """
        # Mapeo de OIDs a sus nombres cortos estándar
        oid_to_name = {
            "commonName": "CN",
            "organizationalUnitName": "OU",
            "organizationName": "O",
            "countryName": "C",
            "localityName": "L",
            "stateOrProvinceName": "ST",
            "serialNumber": "SERIALNUMBER",
            "emailAddress": "E",
        }

        parts = []
        for attr in name:
            oid_name = attr.oid._name
            short_name = oid_to_name.get(oid_name, oid_name)
            # Escapar caracteres especiales según RFC4514
            value = self._escape_dn_value(attr.value)
            parts.append(f"{short_name}={value}")

        # RFC4514 especifica orden inverso (CN primero, C último)
        return ",".join(parts)

    def _escape_dn_value(self, value: str) -> str:
        """Escapa caracteres especiales en un valor DN según RFC4514."""
        # Caracteres que necesitan escape: , + " \ < > ;
        result = value
        # El backslash primero
        result = result.replace("\\", "\\\\")
        result = result.replace(",", "\\,")
        result = result.replace("+", "\\+")
        result = result.replace('"', '\\"')
        result = result.replace("<", "\\<")
        result = result.replace(">", "\\>")
        result = result.replace(";", "\\;")
        # Espacios al inicio/fin
        if result.startswith(" "):
            result = "\\ " + result[1:]
        if result.endswith(" "):
            result = result[:-1] + "\\ "
        return result

    def _get_certificate_pem(self) -> bytes:
        """Obtiene el certificado en formato PEM."""
        return self._certificate.public_bytes(serialization.Encoding.PEM)

    def _get_certificate_der(self) -> bytes:
        """Obtiene el certificado en formato DER (para incluir en XML)."""
        return self._certificate.public_bytes(serialization.Encoding.DER)

    def _sign_data(self, data: bytes) -> bytes:
        """Firma datos con la clave privada usando RSA-SHA1."""
        signature = self._private_key.sign(
            data,
            padding.PKCS1v15(),
            hashes.SHA1()  # SRI requiere SHA1
        )
        return signature

    def _calculate_digest(self, data: bytes) -> bytes:
        """Calcula el digest SHA1 de los datos."""
        return hashlib.sha1(data).digest()

    def _canonicalize(self, element: etree._Element, exclusive: bool = False) -> bytes:
        """Canonicaliza un elemento XML.

        Args:
            element: Elemento XML a canonicalizar
            exclusive: True para C14N exclusivo, False para C14N inclusivo (default)
        """
        return etree.tostring(
            element,
            method="c14n",
            exclusive=exclusive,
            with_comments=False
        )

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
            # Parsear XML
            parser = etree.XMLParser(remove_blank_text=True)
            doc = etree.fromstring(xml_string.encode("utf-8"), parser)

            # Obtener el ID del comprobante
            comprobante_id = doc.get("id", "comprobante")

            # Generar IDs únicos para los elementos de firma
            signature_id = f"Signature{uuid.uuid4().hex[:8]}"
            signed_properties_id = f"SignedProperties{uuid.uuid4().hex[:8]}"
            key_info_id = f"KeyInfo{uuid.uuid4().hex[:8]}"
            reference_id = f"Reference{uuid.uuid4().hex[:8]}"

            # Crear estructura de firma
            signature = self._create_signature_structure(
                doc,
                comprobante_id,
                signature_id,
                signed_properties_id,
                key_info_id,
                reference_id
            )

            # Agregar firma al documento
            doc.append(signature)

            # Generar XML firmado
            return etree.tostring(
                doc,
                encoding="UTF-8",
                xml_declaration=True,
                pretty_print=True
            ).decode("UTF-8")

        except Exception as e:
            logger.error("Error al firmar documento", error=str(e))
            raise SigningError(f"Error al firmar documento: {e}") from e

    def _create_signature_structure(
        self,
        doc: etree._Element,
        comprobante_id: str,
        signature_id: str,
        signed_properties_id: str,
        key_info_id: str,
        reference_id: str
    ) -> etree._Element:
        """Crea la estructura completa de firma XAdES-BES."""

        # Namespace map para los elementos de firma
        nsmap = {
            "ds": NAMESPACES["ds"],
            "etsi": NAMESPACES["etsi"],
        }

        # Crear elemento Signature
        signature = etree.Element(
            "{%s}Signature" % NAMESPACES["ds"],
            nsmap=nsmap,
            Id=signature_id
        )

        # === Object (XAdES) - Crear ANTES de SignedInfo para calcular su digest ===
        xades_object = self._create_xades_object(signed_properties_id, signature_id)

        # === KeyInfo - Crear ANTES de SignedInfo para calcular su digest ===
        key_info = self._create_key_info(key_info_id)

        # === SignedInfo (con las 3 referencias: documento, KeyInfo, SignedProperties) ===
        signed_info = self._create_signed_info(
            doc,
            comprobante_id,
            signed_properties_id,
            key_info_id,
            reference_id,
            xades_object=xades_object,
            key_info=key_info
        )
        signature.append(signed_info)

        # === SignatureValue (placeholder, se calcula después) ===
        signature_value = etree.SubElement(
            signature,
            "{%s}SignatureValue" % NAMESPACES["ds"],
            Id=f"SignatureValue{uuid.uuid4().hex[:8]}"
        )

        # === KeyInfo ===
        signature.append(key_info)

        # Añadir Object XAdES
        signature.append(xades_object)

        # Calcular firma real (C14N inclusivo del SignedInfo)
        signed_info_c14n = self._canonicalize(signed_info, exclusive=False)
        signature_bytes = self._sign_data(signed_info_c14n)
        signature_value.text = base64.b64encode(signature_bytes).decode("ascii")

        return signature

    def _create_signed_info(
        self,
        doc: etree._Element,
        comprobante_id: str,
        signed_properties_id: str,
        key_info_id: str,
        reference_id: str,
        xades_object: etree._Element | None = None,
        key_info: etree._Element | None = None
    ) -> etree._Element:
        """Crea el elemento SignedInfo con las 3 referencias requeridas por XAdES-BES."""

        signed_info = etree.Element(
            "{%s}SignedInfo" % NAMESPACES["ds"],
        )

        # CanonicalizationMethod - C14N inclusivo
        canon_method = etree.SubElement(
            signed_info,
            "{%s}CanonicalizationMethod" % NAMESPACES["ds"],
            Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
        )

        # SignatureMethod
        sig_method = etree.SubElement(
            signed_info,
            "{%s}SignatureMethod" % NAMESPACES["ds"],
            Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"
        )

        # Reference 1: al documento (con enveloped-signature transform)
        ref_doc = etree.SubElement(
            signed_info,
            "{%s}Reference" % NAMESPACES["ds"],
            Id=reference_id,
            URI=f"#{comprobante_id}"
        )

        transforms = etree.SubElement(ref_doc, "{%s}Transforms" % NAMESPACES["ds"])
        etree.SubElement(
            transforms,
            "{%s}Transform" % NAMESPACES["ds"],
            Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"
        )

        etree.SubElement(
            ref_doc,
            "{%s}DigestMethod" % NAMESPACES["ds"],
            Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"
        )

        # Calcular digest del documento (C14N inclusivo)
        doc_c14n = self._canonicalize(doc, exclusive=False)
        doc_digest = self._calculate_digest(doc_c14n)

        digest_value = etree.SubElement(ref_doc, "{%s}DigestValue" % NAMESPACES["ds"])
        digest_value.text = base64.b64encode(doc_digest).decode("ascii")

        # Reference 2: al KeyInfo (certificado X.509)
        if key_info is not None:
            ref_keyinfo = etree.SubElement(
                signed_info,
                "{%s}Reference" % NAMESPACES["ds"],
                URI=f"#{key_info_id}"
            )

            etree.SubElement(
                ref_keyinfo,
                "{%s}DigestMethod" % NAMESPACES["ds"],
                Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"
            )

            # Calcular digest del KeyInfo (C14N inclusivo)
            keyinfo_c14n = self._canonicalize(key_info, exclusive=False)
            keyinfo_digest = self._calculate_digest(keyinfo_c14n)

            digest_value_keyinfo = etree.SubElement(
                ref_keyinfo,
                "{%s}DigestValue" % NAMESPACES["ds"]
            )
            digest_value_keyinfo.text = base64.b64encode(keyinfo_digest).decode("ascii")

        # Reference 3: al SignedProperties (requerido por XAdES-BES)
        if xades_object is not None:
            # Buscar el elemento SignedProperties dentro del Object
            signed_props = xades_object.find(
                ".//{%s}SignedProperties" % NAMESPACES["etsi"]
            )
            if signed_props is not None:
                ref_props = etree.SubElement(
                    signed_info,
                    "{%s}Reference" % NAMESPACES["ds"],
                    URI=f"#{signed_properties_id}",
                    Type="http://uri.etsi.org/01903#SignedProperties"
                )

                etree.SubElement(
                    ref_props,
                    "{%s}DigestMethod" % NAMESPACES["ds"],
                    Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"
                )

                # Calcular digest del SignedProperties (C14N inclusivo)
                props_c14n = self._canonicalize(signed_props, exclusive=False)
                props_digest = self._calculate_digest(props_c14n)

                digest_value_props = etree.SubElement(
                    ref_props,
                    "{%s}DigestValue" % NAMESPACES["ds"]
                )
                digest_value_props.text = base64.b64encode(props_digest).decode("ascii")

        return signed_info

    def _create_key_info(self, key_info_id: str) -> etree._Element:
        """Crea el elemento KeyInfo con el certificado."""

        key_info = etree.Element(
            "{%s}KeyInfo" % NAMESPACES["ds"],
            Id=key_info_id
        )

        x509_data = etree.SubElement(key_info, "{%s}X509Data" % NAMESPACES["ds"])
        x509_cert = etree.SubElement(x509_data, "{%s}X509Certificate" % NAMESPACES["ds"])

        # Certificado en Base64
        cert_der = self._get_certificate_der()
        x509_cert.text = base64.b64encode(cert_der).decode("ascii")

        # KeyValue (opcional pero recomendado)
        key_value = etree.SubElement(key_info, "{%s}KeyValue" % NAMESPACES["ds"])
        rsa_key_value = etree.SubElement(key_value, "{%s}RSAKeyValue" % NAMESPACES["ds"])

        public_key = self._certificate.public_key()
        if isinstance(public_key, rsa.RSAPublicKey):
            public_numbers = public_key.public_numbers()

            modulus = etree.SubElement(rsa_key_value, "{%s}Modulus" % NAMESPACES["ds"])
            modulus.text = base64.b64encode(
                public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
            ).decode("ascii")

            exponent = etree.SubElement(rsa_key_value, "{%s}Exponent" % NAMESPACES["ds"])
            exponent.text = base64.b64encode(
                public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")
            ).decode("ascii")

        return key_info

    def _create_xades_object(
        self,
        signed_properties_id: str,
        signature_id: str
    ) -> etree._Element:
        """Crea el objeto XAdES con las propiedades firmadas."""

        obj = etree.Element("{%s}Object" % NAMESPACES["ds"], Id="XadesObject")

        qualifying_props = etree.SubElement(
            obj,
            "{%s}QualifyingProperties" % NAMESPACES["etsi"],
            Target=f"#{signature_id}"
        )

        signed_props = etree.SubElement(
            qualifying_props,
            "{%s}SignedProperties" % NAMESPACES["etsi"],
            Id=signed_properties_id
        )

        signed_sig_props = etree.SubElement(
            signed_props,
            "{%s}SignedSignatureProperties" % NAMESPACES["etsi"]
        )

        # Tiempo de firma
        signing_time = etree.SubElement(
            signed_sig_props,
            "{%s}SigningTime" % NAMESPACES["etsi"]
        )
        signing_time.text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Certificado de firma
        signing_cert = etree.SubElement(
            signed_sig_props,
            "{%s}SigningCertificate" % NAMESPACES["etsi"]
        )

        cert_elem = etree.SubElement(signing_cert, "{%s}Cert" % NAMESPACES["etsi"])

        cert_digest = etree.SubElement(cert_elem, "{%s}CertDigest" % NAMESPACES["etsi"])

        etree.SubElement(
            cert_digest,
            "{%s}DigestMethod" % NAMESPACES["ds"],
            Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"
        )

        digest_value = etree.SubElement(cert_digest, "{%s}DigestValue" % NAMESPACES["ds"])
        cert_der = self._get_certificate_der()
        digest_value.text = base64.b64encode(self._calculate_digest(cert_der)).decode("ascii")

        # Issuer y Serial
        issuer_serial = etree.SubElement(cert_elem, "{%s}IssuerSerial" % NAMESPACES["etsi"])

        x509_issuer_name = etree.SubElement(
            issuer_serial,
            "{%s}X509IssuerName" % NAMESPACES["ds"]
        )
        # Usar formato RFC4514 para X509IssuerName
        x509_issuer_name.text = self._cert_info.get("issuer_rfc4514", "")

        x509_serial = etree.SubElement(
            issuer_serial,
            "{%s}X509SerialNumber" % NAMESPACES["ds"]
        )
        x509_serial.text = self._cert_info.get("serial_number", "")

        return obj

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


def sign_xml(xml_string: str, cert_path: str, cert_password: str) -> str:
    """
    Función helper para firmar un XML.

    Args:
        xml_string: XML sin firmar
        cert_path: Ruta al certificado .p12
        cert_password: Contraseña del certificado

    Returns:
        XML firmado
    """
    signer = XAdESSigner(cert_path, cert_password)
    return signer.sign(xml_string)
