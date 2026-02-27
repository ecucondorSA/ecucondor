"""
ECUCONDOR - Firmador XAdES-BES para SRI Ecuador (2025)
Replicado exactamente del formato del facturador oficial SRI.
"""

import base64
import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from lxml import etree
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# Namespaces exactos del XML exitoso
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"
NS_XADES141 = "http://uri.etsi.org/01903/v1.4.1#"

NSMAP = {
    'ds': NS_DS,
    'xades': NS_XADES,
    'xades141': NS_XADES141,
}

# Algoritmos SHA-256 (requeridos por SRI 2025)
ALG_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ALG_SIGNATURE = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
ALG_DIGEST = "http://www.w3.org/2001/04/xmlenc#sha256"
ALG_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"


def sha256_digest(data: bytes) -> str:
    """Calcula SHA-256 y retorna en Base64."""
    digest = hashlib.sha256(data).digest()
    return base64.b64encode(digest).decode('ascii')


def c14n(element) -> bytes:
    """Canonicaliza un elemento XML usando C14N inclusivo."""
    return etree.tostring(element, method='c14n', exclusive=False, with_comments=False)


class FirmadorSRI2025:
    """
    Firmador XAdES-BES compatible con SRI Ecuador 2025.
    Replica exactamente la estructura del facturador oficial.
    """

    def __init__(self, cert_path: str, cert_password: str):
        self.cert_path = cert_path
        self.cert_password = cert_password
        self._cargar_certificado()

    def _cargar_certificado(self):
        """Carga el certificado .p12."""
        with open(self.cert_path, 'rb') as f:
            p12_data = f.read()

        self.private_key, self.certificate, _ = pkcs12.load_key_and_certificates(
            p12_data,
            self.cert_password.encode('utf-8')
        )

        if self.certificate is None:
            raise ValueError("No se encontró certificado en el archivo .p12")

        # Certificado en DER para hash
        self.cert_der = self.certificate.public_bytes(serialization.Encoding.DER)

        # Certificado en Base64 (sin saltos de línea)
        self.cert_b64 = base64.b64encode(self.cert_der).decode('ascii')

        # Datos del emisor
        self.issuer_name = self._formatear_issuer()
        self.serial_number = str(self.certificate.serial_number)

    def _formatear_issuer(self) -> str:
        """Formatea el issuer en el orden que espera el SRI."""
        # Orden: CN, OU, O, C
        partes = {}
        for attr in self.certificate.issuer:
            oid_name = attr.oid._name
            if oid_name == 'commonName':
                partes['CN'] = attr.value
            elif oid_name == 'organizationalUnitName':
                partes['OU'] = attr.value
            elif oid_name == 'organizationName':
                partes['O'] = attr.value
            elif oid_name == 'countryName':
                partes['C'] = attr.value

        # Construir en orden específico
        resultado = []
        for key in ['CN', 'OU', 'O', 'C']:
            if key in partes:
                resultado.append(f"{key}={partes[key]}")

        return ','.join(resultado)

    def firmar(self, xml_string: str) -> str:
        """
        Firma un documento XML con XAdES-BES.

        Args:
            xml_string: XML sin firmar

        Returns:
            XML firmado
        """
        # Parsear XML
        parser = etree.XMLParser(remove_blank_text=True)
        root = etree.fromstring(xml_string.encode('utf-8'), parser)

        # Generar ID único para la firma
        sig_id = f"xmldsig-{uuid.uuid4()}"

        # Crear estructura de firma
        signature = self._crear_firma(root, sig_id)

        # Agregar firma al documento
        root.append(signature)

        # Retornar XML firmado (UTF-8 con declaración XML)
        xml_bytes = etree.tostring(root, encoding='UTF-8', xml_declaration=True)
        return xml_bytes.decode('utf-8')

    def _crear_firma(self, root, sig_id: str):
        """Crea el elemento ds:Signature completo."""

        # Crear elemento Signature con namespace solo ds
        signature = etree.Element(
            f"{{{NS_DS}}}Signature",
            nsmap={'ds': NS_DS},
            Id=sig_id
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
            URI="#comprobante"
        )
        transforms = etree.SubElement(ref_comprobante, f"{{{NS_DS}}}Transforms")
        etree.SubElement(transforms, f"{{{NS_DS}}}Transform", Algorithm=ALG_ENVELOPED)
        etree.SubElement(ref_comprobante, f"{{{NS_DS}}}DigestMethod", Algorithm=ALG_DIGEST)

        # Hash del comprobante (sin la firma)
        comprobante_bytes = c14n(root)
        digest_comprobante = sha256_digest(comprobante_bytes)
        etree.SubElement(ref_comprobante, f"{{{NS_DS}}}DigestValue").text = digest_comprobante

        # Reference 2: SignedProperties
        signed_props_id = f"{sig_id}-signedprops"
        ref_props = etree.SubElement(
            signed_info,
            f"{{{NS_DS}}}Reference",
            Type="http://uri.etsi.org/01903#SignedProperties",
            URI=f"#{signed_props_id}"
        )
        etree.SubElement(ref_props, f"{{{NS_DS}}}DigestMethod", Algorithm=ALG_DIGEST)
        # DigestValue se calculará después de crear SignedProperties
        digest_props_elem = etree.SubElement(ref_props, f"{{{NS_DS}}}DigestValue")

        # --- KeyInfo ---
        key_info = etree.SubElement(signature, f"{{{NS_DS}}}KeyInfo")
        x509_data = etree.SubElement(key_info, f"{{{NS_DS}}}X509Data")
        etree.SubElement(x509_data, f"{{{NS_DS}}}X509Certificate").text = self.cert_b64

        # --- Object (XAdES) ---
        obj = etree.SubElement(signature, f"{{{NS_DS}}}Object")
        qualifying_props = etree.SubElement(
            obj,
            f"{{{NS_XADES}}}QualifyingProperties",
            nsmap={'xades': NS_XADES, 'xades141': NS_XADES141},
            Target=f"#{sig_id}"
        )

        # SignedProperties
        signed_props = etree.SubElement(
            qualifying_props,
            f"{{{NS_XADES}}}SignedProperties",
            Id=signed_props_id
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
        etree.SubElement(cert_digest, f"{{{NS_DS}}}DigestValue").text = sha256_digest(self.cert_der)

        issuer_serial = etree.SubElement(cert_elem, f"{{{NS_XADES}}}IssuerSerial")
        etree.SubElement(issuer_serial, f"{{{NS_DS}}}X509IssuerName").text = self.issuer_name
        etree.SubElement(issuer_serial, f"{{{NS_DS}}}X509SerialNumber").text = self.serial_number

        # SignedDataObjectProperties
        signed_data_props = etree.SubElement(signed_props, f"{{{NS_XADES}}}SignedDataObjectProperties")
        data_obj_format = etree.SubElement(
            signed_data_props,
            f"{{{NS_XADES}}}DataObjectFormat",
            ObjectReference=f"#{sig_id}-ref0"
        )
        etree.SubElement(data_obj_format, f"{{{NS_XADES}}}Description").text = "FIRMA DIGITAL SRI"
        etree.SubElement(data_obj_format, f"{{{NS_XADES}}}MimeType").text = "text/xml"
        etree.SubElement(data_obj_format, f"{{{NS_XADES}}}Encoding").text = "UTF-8"

        # Calcular hash de SignedProperties
        signed_props_bytes = c14n(signed_props)
        digest_props_elem.text = sha256_digest(signed_props_bytes)

        # --- SignatureValue ---
        # Canonicalizar SignedInfo y firmar
        signed_info_bytes = c14n(signed_info)
        signature_value = self.private_key.sign(
            signed_info_bytes,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        signature_b64 = base64.b64encode(signature_value).decode('ascii')

        # Insertar SignatureValue después de SignedInfo
        sig_value = etree.Element(f"{{{NS_DS}}}SignatureValue", Id=f"{sig_id}-sigvalue")
        sig_value.text = signature_b64
        signature.insert(1, sig_value)

        return signature


def firmar_xml_sri(xml_string: str, cert_path: str, cert_password: str) -> str:
    """
    Función de conveniencia para firmar XML.

    Args:
        xml_string: XML sin firmar
        cert_path: Ruta al certificado .p12
        cert_password: Contraseña del certificado

    Returns:
        XML firmado
    """
    firmador = FirmadorSRI2025(cert_path, cert_password)
    return firmador.firmar(xml_string)


if __name__ == "__main__":
    # Prueba
    import os
    from pathlib import Path

    cert_path = "/home/edu/ecucondor/certs/firma.p12"

    # Cargar password del .env
    from dotenv import dotenv_values
    env = dotenv_values(Path(__file__).parent.parent.parent / ".env")
    cert_password = env.get("SRI_CERT_PASSWORD", "")

    xml_prueba = '''<?xml version="1.0" encoding="UTF-8"?>
<factura id="comprobante" version="1.1.0">
    <infoTributaria>
        <ambiente>2</ambiente>
        <tipoEmision>1</tipoEmision>
        <razonSocial>ECUCONDOR SAS</razonSocial>
        <ruc>1391937000001</ruc>
        <claveAcceso>2611202501139193700000120010010000000019255120219</claveAcceso>
        <codDoc>01</codDoc>
        <estab>001</estab>
        <ptoEmi>001</ptoEmi>
        <secuencial>000000001</secuencial>
        <dirMatriz>QUITO</dirMatriz>
    </infoTributaria>
</factura>'''

    try:
        xml_firmado = firmar_xml_sri(xml_prueba, cert_path, cert_password)
        print("XML firmado exitosamente")
        print(xml_firmado[:500])
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
