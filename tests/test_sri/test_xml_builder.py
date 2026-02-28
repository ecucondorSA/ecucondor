"""
Tests para el constructor de XML de comprobantes electronicos del SRI.
Pruebas de logica pura (generacion XML), sin DB ni servicios externos.
"""

from datetime import date
from decimal import Decimal

import pytest
from lxml import etree

from src.sri.models import (
    CodigoImpuesto,
    CodigoPorcentajeIVA,
    DetalleFactura,
    Factura,
    FormaPago,
    Impuesto,
    InfoFactura,
    InfoNotaCredito,
    InfoTributaria,
    NotaCredito,
    Pago,
    TipoIdentificacion,
    TotalImpuesto,
)
from src.sri.xml_builder import XMLBuilder, crear_factura_xml, crear_nota_credito_xml


# ============================================================
# Fixtures / Helpers
# ============================================================


def _clave_acceso_test() -> str:
    """Genera una clave de acceso de prueba de 49 digitos."""
    # Estructura: fecha(8) + tipoDoc(2) + ruc(13) + ambiente(1) + estab(3)
    #             + ptoEmi(3) + secuencial(9) + codNumerico(8) + tipoEmision(1) + digVerif(1)
    return "1501202401179253550000100100100000000112345678011"


def _info_tributaria_factura() -> InfoTributaria:
    """InfoTributaria de prueba para factura."""
    return InfoTributaria(
        ambiente="1",
        tipo_emision="1",
        razon_social="ECUCONDOR SAS BIC",
        nombre_comercial="ECUCONDOR",
        ruc="1391937000001",
        clave_acceso=_clave_acceso_test(),
        cod_doc="01",
        estab="001",
        pto_emi="001",
        secuencial="000000001",
        dir_matriz="Quito, Ecuador",
    )


def _info_tributaria_nc() -> InfoTributaria:
    """InfoTributaria de prueba para nota de credito."""
    return InfoTributaria(
        ambiente="1",
        tipo_emision="1",
        razon_social="ECUCONDOR SAS BIC",
        nombre_comercial="ECUCONDOR",
        ruc="1391937000001",
        clave_acceso=_clave_acceso_test(),
        cod_doc="04",
        estab="001",
        pto_emi="001",
        secuencial="000000001",
        dir_matriz="Quito, Ecuador",
    )


def _detalle_con_iva(
    descripcion="Servicio de comision",
    cantidad=Decimal("1"),
    precio=Decimal("100.00"),
    porcentaje_iva=Decimal("15"),
) -> DetalleFactura:
    """Crea un detalle de factura con IVA 15%."""
    precio_total = cantidad * precio
    valor_iva = (precio_total * porcentaje_iva / Decimal("100")).quantize(Decimal("0.01"))
    return DetalleFactura(
        codigo_principal="SERV001",
        descripcion=descripcion,
        cantidad=cantidad,
        precio_unitario=precio,
        descuento=Decimal("0"),
        precio_total_sin_impuesto=precio_total,
        impuestos=[
            Impuesto(
                codigo=CodigoImpuesto.IVA,
                codigo_porcentaje=CodigoPorcentajeIVA.IVA_15,
                tarifa=porcentaje_iva,
                base_imponible=precio_total,
                valor=valor_iva,
            )
        ],
    )


def _detalle_sin_iva(
    descripcion="Producto exento",
    cantidad=Decimal("1"),
    precio=Decimal("50.00"),
) -> DetalleFactura:
    """Crea un detalle de factura sin IVA."""
    precio_total = cantidad * precio
    return DetalleFactura(
        codigo_principal="PROD001",
        descripcion=descripcion,
        cantidad=cantidad,
        precio_unitario=precio,
        descuento=Decimal("0"),
        precio_total_sin_impuesto=precio_total,
        impuestos=[
            Impuesto(
                codigo=CodigoImpuesto.IVA,
                codigo_porcentaje=CodigoPorcentajeIVA.IVA_0,
                tarifa=Decimal("0"),
                base_imponible=precio_total,
                valor=Decimal("0"),
            )
        ],
    )


def _factura_simple(
    subtotal=Decimal("100"),
    iva=Decimal("15"),
) -> Factura:
    """Crea una factura completa de prueba."""
    detalle = _detalle_con_iva(precio=subtotal)
    importe_total = subtotal + iva

    return Factura(
        info_tributaria=_info_tributaria_factura(),
        info_factura=InfoFactura(
            fecha_emision=date(2025, 3, 15),
            obligado_contabilidad="SI",
            tipo_identificacion_comprador=TipoIdentificacion.RUC,
            razon_social_comprador="CLIENTE TEST SA",
            identificacion_comprador="1792535500001",
            direccion_comprador="Av. Principal 456",
            total_sin_impuestos=subtotal,
            total_descuento=Decimal("0"),
            total_con_impuestos=[
                TotalImpuesto(
                    codigo=CodigoImpuesto.IVA,
                    codigo_porcentaje=CodigoPorcentajeIVA.IVA_15,
                    base_imponible=subtotal,
                    tarifa=Decimal("15"),
                    valor=iva,
                )
            ],
            propina=Decimal("0"),
            importe_total=importe_total,
            pagos=[Pago(forma_pago=FormaPago.OTROS, total=importe_total)],
        ),
        detalles=[detalle],
    )


def _parse_xml(xml_str: str) -> etree._Element:
    """Parsea un string XML a un elemento lxml."""
    return etree.fromstring(xml_str.encode("UTF-8"))


# ============================================================
# XMLBuilder.build_factura
# ============================================================


class TestBuildFactura:
    """Tests para la generacion de XML de factura."""

    def test_genera_xml_valido(self):
        """El XML generado debe ser parseable."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)

        # No debe lanzar excepcion
        root = _parse_xml(xml_str)
        assert root is not None

    def test_elemento_raiz_es_factura(self):
        """El elemento raiz debe ser 'factura'."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        assert root.tag == "factura"

    def test_version_factura(self):
        """El atributo version debe ser 2.1.0."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        assert root.get("version") == "2.1.0"

    def test_atributo_id_comprobante(self):
        """El atributo id debe ser 'comprobante'."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        assert root.get("id") == "comprobante"

    def test_contiene_info_tributaria(self):
        """El XML debe contener la seccion infoTributaria."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        info_trib = root.find("infoTributaria")
        assert info_trib is not None

    def test_contiene_info_factura(self):
        """El XML debe contener la seccion infoFactura."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        info_fact = root.find("infoFactura")
        assert info_fact is not None

    def test_contiene_detalles(self):
        """El XML debe contener la seccion detalles."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        detalles = root.find("detalles")
        assert detalles is not None

    def test_info_tributaria_ruc(self):
        """El RUC en infoTributaria debe ser correcto."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        ruc = root.find("infoTributaria/ruc")
        assert ruc is not None
        assert ruc.text == "1391937000001"

    def test_info_tributaria_razon_social(self):
        """La razon social debe estar en el XML."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        rs = root.find("infoTributaria/razonSocial")
        assert rs is not None
        assert rs.text == "ECUCONDOR SAS BIC"

    def test_info_tributaria_clave_acceso(self):
        """La clave de acceso debe estar incluida."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        clave = root.find("infoTributaria/claveAcceso")
        assert clave is not None
        assert len(clave.text) == 49

    def test_info_tributaria_cod_doc_factura(self):
        """El codigo de documento debe ser '01' (factura)."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        cod_doc = root.find("infoTributaria/codDoc")
        assert cod_doc.text == "01"

    def test_fecha_formato_dd_mm_yyyy(self):
        """La fecha de emision debe estar en formato dd/mm/yyyy."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        fecha = root.find("infoFactura/fechaEmision")
        assert fecha is not None
        assert fecha.text == "15/03/2025"

    def test_total_sin_impuestos(self):
        """El total sin impuestos debe coincidir."""
        factura = _factura_simple(subtotal=Decimal("200"), iva=Decimal("30"))
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        total = root.find("infoFactura/totalSinImpuestos")
        assert total is not None
        assert total.text == "200.00"

    def test_importe_total_con_iva(self):
        """El importe total incluye IVA."""
        factura = _factura_simple(subtotal=Decimal("100"), iva=Decimal("15"))
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        importe = root.find("infoFactura/importeTotal")
        assert importe is not None
        assert importe.text == "115.00"

    def test_total_con_impuestos_seccion(self):
        """Debe existir la seccion totalConImpuestos."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        total_imp = root.find("infoFactura/totalConImpuestos")
        assert total_imp is not None

        totales = total_imp.findall("totalImpuesto")
        assert len(totales) >= 1

    def test_total_impuesto_iva_15(self):
        """El total de impuesto IVA 15% tiene los campos correctos."""
        factura = _factura_simple(subtotal=Decimal("100"), iva=Decimal("15"))
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        total_imp = root.find("infoFactura/totalConImpuestos/totalImpuesto")
        assert total_imp is not None

        codigo = total_imp.find("codigo")
        assert codigo.text == "2"  # IVA

        cod_pct = total_imp.find("codigoPorcentaje")
        assert cod_pct.text == "4"  # IVA 15%

        base = total_imp.find("baseImponible")
        assert base.text == "100.00"

        valor = total_imp.find("valor")
        assert valor.text == "15.00"

    def test_detalle_descripcion(self):
        """El detalle debe tener la descripcion correcta."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        desc = root.find("detalles/detalle/descripcion")
        assert desc is not None
        assert desc.text == "Servicio de comision"

    def test_detalle_cantidad_formato(self):
        """La cantidad del detalle debe tener 6 decimales."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        cantidad = root.find("detalles/detalle/cantidad")
        assert cantidad is not None
        assert cantidad.text == "1.000000"

    def test_detalle_precio_unitario_formato(self):
        """El precio unitario debe tener 6 decimales."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        precio = root.find("detalles/detalle/precioUnitario")
        assert precio is not None
        assert precio.text == "100.000000"

    def test_pagos_seccion(self):
        """Debe existir la seccion pagos."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        pagos = root.find("infoFactura/pagos")
        assert pagos is not None

        pago = pagos.find("pago")
        assert pago is not None

        forma = pago.find("formaPago")
        assert forma.text == "20"  # OTROS

    def test_moneda_dolar(self):
        """La moneda debe ser DOLAR."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        moneda = root.find("infoFactura/moneda")
        assert moneda.text == "DOLAR"

    def test_obligado_contabilidad(self):
        """obligadoContabilidad debe ser SI."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        obligado = root.find("infoFactura/obligadoContabilidad")
        assert obligado.text == "SI"

    def test_xml_contiene_declaracion(self):
        """El XML debe contener la declaracion XML UTF-8."""
        factura = _factura_simple()
        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)

        assert xml_str.startswith("<?xml version='1.0' encoding='UTF-8'?>")

    def test_info_adicional_con_email(self):
        """Si tiene info adicional, debe aparecer en el XML."""
        factura = _factura_simple()
        factura.info_adicional = {"Email": "test@example.com"}

        builder = XMLBuilder()
        xml_str = builder.build_factura(factura)
        root = _parse_xml(xml_str)

        info_ad = root.find("infoAdicional")
        assert info_ad is not None

        campos = info_ad.findall("campoAdicional")
        assert len(campos) == 1
        assert campos[0].get("nombre") == "Email"
        assert campos[0].text == "test@example.com"


# ============================================================
# crear_factura_xml (helper)
# ============================================================


class TestCrearFacturaXml:
    """Tests para la funcion helper crear_factura_xml."""

    def test_genera_xml_string(self):
        """Retorna un string XML valido."""
        xml_str = crear_factura_xml(
            ruc="1391937000001",
            razon_social="ECUCONDOR SAS BIC",
            direccion_matriz="Quito, Ecuador",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
            clave_acceso=_clave_acceso_test(),
            fecha_emision=date(2025, 6, 1),
            cliente_tipo_id=TipoIdentificacion.RUC,
            cliente_identificacion="1792535500001",
            cliente_razon_social="CLIENTE TEST",
            items=[
                {
                    "codigo": "SERV001",
                    "descripcion": "Servicio de comision P2P",
                    "cantidad": 1,
                    "precio_unitario": 100,
                    "aplica_iva": True,
                    "porcentaje_iva": 15,
                }
            ],
        )

        assert isinstance(xml_str, str)
        root = _parse_xml(xml_str)
        assert root.tag == "factura"

    def test_estructura_completa(self):
        """La estructura tiene las 3 secciones principales."""
        xml_str = crear_factura_xml(
            ruc="1391937000001",
            razon_social="ECUCONDOR SAS BIC",
            direccion_matriz="Quito, Ecuador",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
            clave_acceso=_clave_acceso_test(),
            fecha_emision=date(2025, 1, 1),
            cliente_tipo_id=TipoIdentificacion.CONSUMIDOR_FINAL,
            cliente_identificacion="9999999999999",
            cliente_razon_social="CONSUMIDOR FINAL",
            items=[{"descripcion": "Servicio", "cantidad": 1, "precio_unitario": 50}],
        )

        root = _parse_xml(xml_str)
        assert root.find("infoTributaria") is not None
        assert root.find("infoFactura") is not None
        assert root.find("detalles") is not None

    def test_calculo_iva_15_correcto(self):
        """IVA 15% se calcula correctamente en el helper."""
        xml_str = crear_factura_xml(
            ruc="1391937000001",
            razon_social="ECUCONDOR SAS BIC",
            direccion_matriz="Quito, Ecuador",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=2,
            clave_acceso=_clave_acceso_test(),
            fecha_emision=date(2025, 1, 15),
            cliente_tipo_id=TipoIdentificacion.RUC,
            cliente_identificacion="1792535500001",
            cliente_razon_social="EMPRESA TEST",
            items=[
                {
                    "descripcion": "Servicio A",
                    "cantidad": 2,
                    "precio_unitario": 100,
                    "aplica_iva": True,
                    "porcentaje_iva": 15,
                }
            ],
        )

        root = _parse_xml(xml_str)

        # Subtotal: 2 * 100 = 200
        total_sin = root.find("infoFactura/totalSinImpuestos")
        assert total_sin.text == "200.00"

        # IVA: 200 * 15% = 30
        total_imp = root.find("infoFactura/totalConImpuestos/totalImpuesto")
        valor_iva = total_imp.find("valor")
        assert valor_iva.text == "30.00"

        # Total: 200 + 30 = 230
        importe = root.find("infoFactura/importeTotal")
        assert importe.text == "230.00"

    def test_item_sin_iva(self):
        """Item sin IVA genera totalImpuesto con codigoPorcentaje 0."""
        xml_str = crear_factura_xml(
            ruc="1391937000001",
            razon_social="ECUCONDOR SAS BIC",
            direccion_matriz="Quito, Ecuador",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=3,
            clave_acceso=_clave_acceso_test(),
            fecha_emision=date(2025, 1, 1),
            cliente_tipo_id=TipoIdentificacion.CONSUMIDOR_FINAL,
            cliente_identificacion="9999999999999",
            cliente_razon_social="CONSUMIDOR FINAL",
            items=[
                {
                    "descripcion": "Producto tarifa 0",
                    "cantidad": 1,
                    "precio_unitario": 80,
                    "aplica_iva": False,
                }
            ],
        )

        root = _parse_xml(xml_str)

        total_imp = root.find("infoFactura/totalConImpuestos/totalImpuesto")
        cod_pct = total_imp.find("codigoPorcentaje")
        assert cod_pct.text == "0"  # IVA 0%

        valor = total_imp.find("valor")
        assert valor.text == "0.00"

    def test_secuencial_relleno_ceros(self):
        """El secuencial se rellena con ceros a 9 digitos."""
        xml_str = crear_factura_xml(
            ruc="1391937000001",
            razon_social="TEST",
            direccion_matriz="Quito",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=42,
            clave_acceso=_clave_acceso_test(),
            fecha_emision=date(2025, 1, 1),
            cliente_tipo_id=TipoIdentificacion.CONSUMIDOR_FINAL,
            cliente_identificacion="9999999999999",
            cliente_razon_social="CONSUMIDOR FINAL",
            items=[{"descripcion": "Item", "cantidad": 1, "precio_unitario": 10}],
        )

        root = _parse_xml(xml_str)
        secuencial = root.find("infoTributaria/secuencial")
        assert secuencial.text == "000000042"

    def test_info_adicional_email(self):
        """El email del cliente aparece en infoAdicional."""
        xml_str = crear_factura_xml(
            ruc="1391937000001",
            razon_social="TEST",
            direccion_matriz="Quito",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
            clave_acceso=_clave_acceso_test(),
            fecha_emision=date(2025, 1, 1),
            cliente_tipo_id=TipoIdentificacion.CONSUMIDOR_FINAL,
            cliente_identificacion="9999999999999",
            cliente_razon_social="CONSUMIDOR FINAL",
            cliente_email="test@example.com",
            items=[{"descripcion": "Item", "cantidad": 1, "precio_unitario": 10}],
        )

        root = _parse_xml(xml_str)
        info_ad = root.find("infoAdicional")
        assert info_ad is not None

        campo = info_ad.find("campoAdicional")
        assert campo.get("nombre") == "Email"
        assert campo.text == "test@example.com"

    def test_multiples_items(self):
        """Factura con multiples items genera multiples detalles."""
        xml_str = crear_factura_xml(
            ruc="1391937000001",
            razon_social="TEST",
            direccion_matriz="Quito",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
            clave_acceso=_clave_acceso_test(),
            fecha_emision=date(2025, 1, 1),
            cliente_tipo_id=TipoIdentificacion.CONSUMIDOR_FINAL,
            cliente_identificacion="9999999999999",
            cliente_razon_social="CONSUMIDOR FINAL",
            items=[
                {"descripcion": "Servicio A", "cantidad": 1, "precio_unitario": 100, "aplica_iva": True},
                {"descripcion": "Servicio B", "cantidad": 2, "precio_unitario": 50, "aplica_iva": True},
            ],
        )

        root = _parse_xml(xml_str)
        detalles = root.findall("detalles/detalle")
        assert len(detalles) == 2


# ============================================================
# XMLBuilder.build_nota_credito
# ============================================================


class TestBuildNotaCredito:
    """Tests para la generacion de XML de nota de credito."""

    def _nc_simple(self) -> NotaCredito:
        """Crea una nota de credito de prueba."""
        subtotal = Decimal("100")
        iva = Decimal("15")
        valor_mod = subtotal + iva

        return NotaCredito(
            info_tributaria=_info_tributaria_nc(),
            info_nota_credito=InfoNotaCredito(
                fecha_emision=date(2025, 4, 10),
                tipo_identificacion_comprador=TipoIdentificacion.RUC,
                razon_social_comprador="CLIENTE TEST SA",
                identificacion_comprador="1792535500001",
                obligado_contabilidad="SI",
                cod_doc_modificado="01",
                num_doc_modificado="001-001-000000002",
                fecha_emision_doc_sustento=date(2025, 3, 15),
                total_sin_impuestos=subtotal,
                valor_modificacion=valor_mod,
                total_con_impuestos=[
                    TotalImpuesto(
                        codigo=CodigoImpuesto.IVA,
                        codigo_porcentaje=CodigoPorcentajeIVA.IVA_15,
                        base_imponible=subtotal,
                        tarifa=Decimal("15"),
                        valor=iva,
                    )
                ],
                motivo="Anulacion por error en facturacion",
            ),
            detalles=[_detalle_con_iva()],
        )

    def test_genera_xml_valido(self):
        """El XML de NC debe ser parseable."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)

        root = _parse_xml(xml_str)
        assert root is not None

    def test_elemento_raiz_es_nota_credito(self):
        """El elemento raiz debe ser 'notaCredito'."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        assert root.tag == "notaCredito"

    def test_version_nota_credito(self):
        """La version de NC debe ser 1.1.0."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        assert root.get("version") == "1.1.0"

    def test_cod_doc_modificado(self):
        """codDocModificado debe ser '01' (factura)."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        cod = root.find("infoNotaCredito/codDocModificado")
        assert cod is not None
        assert cod.text == "01"

    def test_num_doc_modificado(self):
        """numDocModificado debe contener el numero de factura."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        num = root.find("infoNotaCredito/numDocModificado")
        assert num is not None
        assert num.text == "001-001-000000002"

    def test_motivo(self):
        """El motivo de la NC debe estar presente."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        motivo = root.find("infoNotaCredito/motivo")
        assert motivo is not None
        assert motivo.text == "Anulacion por error en facturacion"

    def test_fecha_emision_doc_sustento(self):
        """La fecha del documento sustento debe estar en formato dd/mm/yyyy."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        fecha = root.find("infoNotaCredito/fechaEmisionDocSustento")
        assert fecha is not None
        assert fecha.text == "15/03/2025"

    def test_valor_modificacion(self):
        """valorModificacion debe ser subtotal + IVA."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        val_mod = root.find("infoNotaCredito/valorModificacion")
        assert val_mod is not None
        assert val_mod.text == "115.00"

    def test_total_sin_impuestos_nc(self):
        """totalSinImpuestos de la NC debe ser correcto."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        total = root.find("infoNotaCredito/totalSinImpuestos")
        assert total is not None
        assert total.text == "100.00"

    def test_contiene_info_tributaria(self):
        """La NC debe contener infoTributaria."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        assert root.find("infoTributaria") is not None

    def test_cod_doc_04(self):
        """El codDoc en infoTributaria debe ser '04' (nota de credito)."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        cod_doc = root.find("infoTributaria/codDoc")
        assert cod_doc.text == "04"

    def test_detalles_con_codigo_interno(self):
        """En NC, los detalles usan codigoInterno en lugar de codigoPrincipal."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        detalle = root.find("detalles/detalle")
        assert detalle is not None

        # En NC: codigoInterno en vez de codigoPrincipal
        codigo_interno = detalle.find("codigoInterno")
        assert codigo_interno is not None

        # No debe existir codigoPrincipal
        codigo_principal = detalle.find("codigoPrincipal")
        assert codigo_principal is None

    def test_nc_total_con_impuestos_sin_tarifa(self):
        """En NC, totalConImpuestos NO incluye tarifa."""
        nc = self._nc_simple()
        builder = XMLBuilder()
        xml_str = builder.build_nota_credito(nc)
        root = _parse_xml(xml_str)

        total_imp = root.find("infoNotaCredito/totalConImpuestos/totalImpuesto")
        assert total_imp is not None

        # En NC, include_tarifa=False, asi que no debe tener tarifa
        tarifa = total_imp.find("tarifa")
        assert tarifa is None


# ============================================================
# crear_nota_credito_xml (helper)
# ============================================================


class TestCrearNotaCreditoXml:
    """Tests para la funcion helper crear_nota_credito_xml."""

    def test_genera_xml_string(self):
        """Retorna un string XML valido."""
        xml_str = crear_nota_credito_xml(
            ruc="1391937000001",
            razon_social="ECUCONDOR SAS BIC",
            direccion_matriz="Quito, Ecuador",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
            clave_acceso=_clave_acceso_test(),
            fecha_emision=date(2025, 5, 1),
            cliente_tipo_id=TipoIdentificacion.RUC,
            cliente_identificacion="1792535500001",
            cliente_razon_social="CLIENTE TEST",
            num_doc_modificado="001-001-000000005",
            fecha_emision_doc_sustento=date(2025, 4, 15),
            motivo="Devolucion parcial",
            items=[
                {
                    "descripcion": "Servicio devuelto",
                    "cantidad": 1,
                    "precio_unitario": 200,
                    "aplica_iva": True,
                    "porcentaje_iva": 15,
                }
            ],
        )

        assert isinstance(xml_str, str)
        root = _parse_xml(xml_str)
        assert root.tag == "notaCredito"

    def test_campos_nc_especificos(self):
        """La NC tiene los campos especificos correctos."""
        xml_str = crear_nota_credito_xml(
            ruc="1391937000001",
            razon_social="ECUCONDOR SAS BIC",
            direccion_matriz="Quito, Ecuador",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=10,
            clave_acceso=_clave_acceso_test(),
            fecha_emision=date(2025, 5, 1),
            num_doc_modificado="001-001-000000005",
            fecha_emision_doc_sustento=date(2025, 4, 1),
            motivo="Anulacion total",
            items=[
                {"descripcion": "Servicio", "cantidad": 1, "precio_unitario": 100},
            ],
        )

        root = _parse_xml(xml_str)
        info_nc = root.find("infoNotaCredito")

        assert info_nc.find("codDocModificado").text == "01"
        assert info_nc.find("numDocModificado").text == "001-001-000000005"
        assert info_nc.find("fechaEmisionDocSustento").text == "01/04/2025"
        assert info_nc.find("motivo").text == "Anulacion total"

    def test_calculo_iva_nc(self):
        """IVA 15% se calcula correctamente en la NC."""
        xml_str = crear_nota_credito_xml(
            ruc="1391937000001",
            razon_social="TEST",
            direccion_matriz="Quito",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
            clave_acceso=_clave_acceso_test(),
            num_doc_modificado="001-001-000000001",
            items=[
                {
                    "descripcion": "Servicio",
                    "cantidad": 1,
                    "precio_unitario": 200,
                    "aplica_iva": True,
                    "porcentaje_iva": 15,
                }
            ],
        )

        root = _parse_xml(xml_str)
        info_nc = root.find("infoNotaCredito")

        assert info_nc.find("totalSinImpuestos").text == "200.00"
        assert info_nc.find("valorModificacion").text == "230.00"

        total_imp = info_nc.find("totalConImpuestos/totalImpuesto")
        assert total_imp.find("valor").text == "30.00"
        assert total_imp.find("baseImponible").text == "200.00"

    def test_cod_doc_04_en_info_tributaria(self):
        """El cod_doc en infoTributaria es '04' para NC."""
        xml_str = crear_nota_credito_xml(
            ruc="1391937000001",
            razon_social="TEST",
            direccion_matriz="Quito",
            ambiente="1",
            establecimiento="001",
            punto_emision="001",
            secuencial=1,
            clave_acceso=_clave_acceso_test(),
            num_doc_modificado="001-001-000000001",
            items=[{"descripcion": "Item", "cantidad": 1, "precio_unitario": 10}],
        )

        root = _parse_xml(xml_str)
        cod_doc = root.find("infoTributaria/codDoc")
        assert cod_doc.text == "04"
