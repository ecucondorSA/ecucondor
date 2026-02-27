"""
ECUCONDOR - Constructor de XML para Comprobantes Electrónicos SRI
Genera documentos XML según el esquema v2.1.0 del SRI Ecuador.
"""

from datetime import date
from decimal import Decimal
from typing import Any

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


def _decimal_to_str(value: Decimal | float, decimals: int = 2) -> str:
    """Convierte un decimal a string con el número especificado de decimales."""
    if isinstance(value, float):
        value = Decimal(str(value))
    return f"{value:.{decimals}f}"


def _add_element(parent: etree._Element, tag: str, text: str | None) -> etree._Element | None:
    """Agrega un elemento hijo con texto si el texto no es None."""
    if text is not None and text != "":
        elem = etree.SubElement(parent, tag)
        elem.text = str(text)
        return elem
    return None


def _add_required_element(parent: etree._Element, tag: str, text: str) -> etree._Element:
    """Agrega un elemento hijo requerido."""
    elem = etree.SubElement(parent, tag)
    elem.text = str(text)
    return elem


class XMLBuilder:
    """Constructor de documentos XML para el SRI."""

    # Versiones de esquema por tipo de comprobante
    VERSIONES = {
        "01": "2.1.0",  # Factura
        "03": "1.1.0",  # Liquidación de Compra
        "04": "1.1.0",  # Nota de Crédito
        "05": "1.0.0",  # Nota de Débito
        "06": "1.1.0",  # Guía de Remisión
        "07": "2.0.0",  # Comprobante de Retención
    }

    def __init__(self) -> None:
        """Inicializa el constructor."""
        pass

    def build_factura(self, factura: Factura) -> str:
        """
        Construye el XML de una factura electrónica.

        Args:
            factura: Modelo de factura con todos los datos

        Returns:
            String XML del documento sin firmar
        """
        # Crear elemento raíz
        root = etree.Element(
            "factura",
            id="comprobante",
            version=self.VERSIONES["01"]
        )

        # Agregar secciones
        self._add_info_tributaria(root, factura.info_tributaria)
        self._add_info_factura(root, factura.info_factura)
        self._add_detalles(root, factura.detalles)

        if factura.info_adicional:
            self._add_info_adicional(root, factura.info_adicional)

        # Generar XML string
        return etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True
        ).decode("UTF-8")

    def _add_info_tributaria(
        self,
        root: etree._Element,
        info: InfoTributaria
    ) -> None:
        """Agrega la sección infoTributaria al XML."""
        info_trib = etree.SubElement(root, "infoTributaria")

        _add_required_element(info_trib, "ambiente", info.ambiente)
        _add_required_element(info_trib, "tipoEmision", info.tipo_emision)
        _add_required_element(info_trib, "razonSocial", info.razon_social)
        _add_element(info_trib, "nombreComercial", info.nombre_comercial)
        _add_required_element(info_trib, "ruc", info.ruc)
        _add_required_element(info_trib, "claveAcceso", info.clave_acceso or "")
        _add_required_element(info_trib, "codDoc", info.cod_doc)
        _add_required_element(info_trib, "estab", info.estab)
        _add_required_element(info_trib, "ptoEmi", info.pto_emi)
        _add_required_element(info_trib, "secuencial", info.secuencial)
        _add_required_element(info_trib, "dirMatriz", info.dir_matriz)

    def _add_info_factura(
        self,
        root: etree._Element,
        info: InfoFactura
    ) -> None:
        """Agrega la sección infoFactura al XML."""
        info_fact = etree.SubElement(root, "infoFactura")

        # Fecha en formato dd/mm/aaaa
        fecha_str = info.fecha_emision.strftime("%d/%m/%Y")
        _add_required_element(info_fact, "fechaEmision", fecha_str)

        _add_element(info_fact, "dirEstablecimiento", info.dir_establecimiento)
        _add_element(info_fact, "contribuyenteEspecial", info.contribuyente_especial)
        _add_required_element(info_fact, "obligadoContabilidad", info.obligado_contabilidad)

        # Tipo de identificación del comprador
        _add_required_element(
            info_fact,
            "tipoIdentificacionComprador",
            info.tipo_identificacion_comprador.value
        )

        _add_element(info_fact, "guiaRemision", info.guia_remision)
        _add_required_element(info_fact, "razonSocialComprador", info.razon_social_comprador)
        _add_required_element(info_fact, "identificacionComprador", info.identificacion_comprador)
        _add_element(info_fact, "direccionComprador", info.direccion_comprador)

        _add_required_element(
            info_fact,
            "totalSinImpuestos",
            _decimal_to_str(info.total_sin_impuestos)
        )
        _add_required_element(
            info_fact,
            "totalDescuento",
            _decimal_to_str(info.total_descuento)
        )

        # Total con impuestos
        self._add_total_con_impuestos(info_fact, info.total_con_impuestos)

        _add_required_element(info_fact, "propina", _decimal_to_str(info.propina))
        _add_required_element(info_fact, "importeTotal", _decimal_to_str(info.importe_total))
        _add_required_element(info_fact, "moneda", info.moneda)

        # Pagos
        self._add_pagos(info_fact, info.pagos)

    def _add_total_con_impuestos(
        self,
        parent: etree._Element,
        totales: list[TotalImpuesto],
        include_tarifa: bool = True,
    ) -> None:
        """Agrega la sección totalConImpuestos.

        Args:
            parent: Elemento padre XML
            totales: Lista de totales de impuestos
            include_tarifa: Si True, incluye tarifa y descuentoAdicional (factura).
                           Si False, solo codigo/codigoPorcentaje/baseImponible/valor (NC).
        """
        total_impuestos = etree.SubElement(parent, "totalConImpuestos")

        for total in totales:
            total_imp = etree.SubElement(total_impuestos, "totalImpuesto")
            _add_required_element(total_imp, "codigo", total.codigo.value)
            _add_required_element(total_imp, "codigoPorcentaje", total.codigo_porcentaje.value)

            if include_tarifa:
                if total.descuento_adicional > 0:
                    _add_element(
                        total_imp,
                        "descuentoAdicional",
                        _decimal_to_str(total.descuento_adicional)
                    )

            _add_required_element(total_imp, "baseImponible", _decimal_to_str(total.base_imponible))

            if include_tarifa:
                _add_required_element(total_imp, "tarifa", _decimal_to_str(total.tarifa, 0))

            _add_required_element(total_imp, "valor", _decimal_to_str(total.valor))

    def _add_pagos(self, parent: etree._Element, pagos: list[Pago]) -> None:
        """Agrega la sección pagos."""
        pagos_elem = etree.SubElement(parent, "pagos")

        for pago in pagos:
            pago_elem = etree.SubElement(pagos_elem, "pago")
            _add_required_element(pago_elem, "formaPago", pago.forma_pago.value)
            _add_required_element(pago_elem, "total", _decimal_to_str(pago.total))

            if pago.plazo is not None:
                _add_element(pago_elem, "plazo", str(pago.plazo))
            if pago.unidad_tiempo:
                _add_element(pago_elem, "unidadTiempo", pago.unidad_tiempo)

    def _add_detalles(
        self,
        root: etree._Element,
        detalles: list[DetalleFactura],
        tag_codigo_principal: str = "codigoPrincipal",
        tag_codigo_auxiliar: str = "codigoAuxiliar",
    ) -> None:
        """Agrega la sección detalles al XML.

        Args:
            root: Elemento padre
            detalles: Lista de detalles
            tag_codigo_principal: Tag para código principal (factura: codigoPrincipal, NC: codigoInterno)
            tag_codigo_auxiliar: Tag para código auxiliar (factura: codigoAuxiliar, NC: codigoAdicional)
        """
        detalles_elem = etree.SubElement(root, "detalles")

        for detalle in detalles:
            det = etree.SubElement(detalles_elem, "detalle")

            _add_element(det, tag_codigo_principal, detalle.codigo_principal)
            _add_element(det, tag_codigo_auxiliar, detalle.codigo_auxiliar)
            _add_required_element(det, "descripcion", detalle.descripcion)
            _add_required_element(det, "cantidad", _decimal_to_str(detalle.cantidad, 6))
            _add_required_element(det, "precioUnitario", _decimal_to_str(detalle.precio_unitario, 6))
            _add_required_element(det, "descuento", _decimal_to_str(detalle.descuento))
            _add_required_element(
                det,
                "precioTotalSinImpuesto",
                _decimal_to_str(detalle.precio_total_sin_impuesto)
            )

            # Impuestos del detalle
            if detalle.impuestos:
                self._add_impuestos_detalle(det, detalle.impuestos)

            # Detalles adicionales
            if detalle.detalles_adicionales:
                self._add_detalles_adicionales(det, detalle.detalles_adicionales)

    def _add_impuestos_detalle(
        self,
        parent: etree._Element,
        impuestos: list[Impuesto]
    ) -> None:
        """Agrega los impuestos de un detalle."""
        impuestos_elem = etree.SubElement(parent, "impuestos")

        for imp in impuestos:
            impuesto = etree.SubElement(impuestos_elem, "impuesto")
            _add_required_element(impuesto, "codigo", imp.codigo.value)
            _add_required_element(impuesto, "codigoPorcentaje", imp.codigo_porcentaje.value)
            _add_required_element(impuesto, "tarifa", _decimal_to_str(imp.tarifa, 0))
            _add_required_element(impuesto, "baseImponible", _decimal_to_str(imp.base_imponible))
            _add_required_element(impuesto, "valor", _decimal_to_str(imp.valor))

    def _add_detalles_adicionales(
        self,
        parent: etree._Element,
        detalles: dict[str, str]
    ) -> None:
        """Agrega detalles adicionales de un item."""
        det_adicionales = etree.SubElement(parent, "detallesAdicionales")

        for nombre, valor in detalles.items():
            det_ad = etree.SubElement(det_adicionales, "detAdicional")
            det_ad.set("nombre", nombre[:300])
            det_ad.set("valor", str(valor)[:300])

    def build_nota_credito(self, nc: NotaCredito) -> str:
        """
        Construye el XML de una nota de crédito electrónica.

        Args:
            nc: Modelo de nota de crédito con todos los datos

        Returns:
            String XML del documento sin firmar
        """
        root = etree.Element(
            "notaCredito",
            id="comprobante",
            version=self.VERSIONES["04"]
        )

        self._add_info_tributaria(root, nc.info_tributaria)
        self._add_info_nota_credito(root, nc.info_nota_credito)
        self._add_detalles(
            root, nc.detalles,
            tag_codigo_principal="codigoInterno",
            tag_codigo_auxiliar="codigoAdicional",
        )

        if nc.info_adicional:
            self._add_info_adicional(root, nc.info_adicional)

        return etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=True,
            pretty_print=True
        ).decode("UTF-8")

    def _add_info_nota_credito(
        self,
        root: etree._Element,
        info: InfoNotaCredito
    ) -> None:
        """Agrega la sección infoNotaCredito al XML."""
        info_nc = etree.SubElement(root, "infoNotaCredito")

        fecha_str = info.fecha_emision.strftime("%d/%m/%Y")
        _add_required_element(info_nc, "fechaEmision", fecha_str)

        _add_element(info_nc, "dirEstablecimiento", info.dir_establecimiento)
        _add_required_element(
            info_nc,
            "tipoIdentificacionComprador",
            info.tipo_identificacion_comprador.value
        )
        _add_required_element(info_nc, "razonSocialComprador", info.razon_social_comprador)
        _add_required_element(info_nc, "identificacionComprador", info.identificacion_comprador)
        _add_element(info_nc, "contribuyenteEspecial", info.contribuyente_especial)
        _add_required_element(info_nc, "obligadoContabilidad", info.obligado_contabilidad)

        # Documento modificado
        _add_required_element(info_nc, "codDocModificado", info.cod_doc_modificado)
        _add_required_element(info_nc, "numDocModificado", info.num_doc_modificado)
        fecha_sustento_str = info.fecha_emision_doc_sustento.strftime("%d/%m/%Y")
        _add_required_element(info_nc, "fechaEmisionDocSustento", fecha_sustento_str)

        _add_required_element(
            info_nc, "totalSinImpuestos", _decimal_to_str(info.total_sin_impuestos)
        )
        _add_required_element(
            info_nc, "valorModificacion", _decimal_to_str(info.valor_modificacion)
        )
        _add_required_element(info_nc, "moneda", info.moneda)

        self._add_total_con_impuestos(info_nc, info.total_con_impuestos, include_tarifa=False)

        _add_required_element(info_nc, "motivo", info.motivo)

    def _add_info_adicional(
        self,
        root: etree._Element,
        info: dict[str, str]
    ) -> None:
        """Agrega la sección infoAdicional al XML."""
        info_adicional = etree.SubElement(root, "infoAdicional")

        for nombre, valor in info.items():
            campo = etree.SubElement(info_adicional, "campoAdicional")
            campo.set("nombre", nombre[:300])
            campo.text = str(valor)[:300]


def crear_factura_xml(
    # Info Tributaria
    ruc: str,
    razon_social: str,
    direccion_matriz: str,
    ambiente: str,
    establecimiento: str,
    punto_emision: str,
    secuencial: int,
    clave_acceso: str,
    nombre_comercial: str | None = None,
    # Info Factura
    fecha_emision: date | None = None,
    cliente_tipo_id: TipoIdentificacion = TipoIdentificacion.RUC,
    cliente_identificacion: str = "",
    cliente_razon_social: str = "",
    cliente_direccion: str | None = None,
    cliente_email: str | None = None,
    obligado_contabilidad: str = "SI",
    contribuyente_especial: str | None = None,
    # Items
    items: list[dict[str, Any]] | None = None,
    # Pago
    forma_pago: FormaPago = FormaPago.OTROS,
    # Adicional
    info_adicional: dict[str, str] | None = None,
) -> str:
    """
    Función helper para crear el XML de una factura de manera simplificada.

    Args:
        ruc: RUC del emisor
        razon_social: Razón social del emisor
        direccion_matriz: Dirección de la matriz
        ambiente: '1' para pruebas, '2' para producción
        establecimiento: Código de establecimiento (ej: '001')
        punto_emision: Código de punto de emisión (ej: '001')
        secuencial: Número secuencial de la factura
        clave_acceso: Clave de acceso de 49 dígitos
        nombre_comercial: Nombre comercial (opcional)
        fecha_emision: Fecha de emisión (default: hoy)
        cliente_tipo_id: Tipo de identificación del cliente
        cliente_identificacion: Número de identificación del cliente
        cliente_razon_social: Razón social/nombre del cliente
        cliente_direccion: Dirección del cliente (opcional)
        cliente_email: Email del cliente (opcional)
        obligado_contabilidad: 'SI' o 'NO'
        contribuyente_especial: Número de contribuyente especial (opcional)
        items: Lista de items con: descripcion, cantidad, precio_unitario,
               descuento (opcional), aplica_iva (default True),
               porcentaje_iva (default 15)
        forma_pago: Forma de pago
        info_adicional: Información adicional a incluir

    Returns:
        String XML del documento sin firmar
    """
    from datetime import date as date_type

    if fecha_emision is None:
        fecha_emision = date_type.today()

    if items is None:
        items = []

    # Calcular totales
    subtotal_sin_impuestos = Decimal("0")
    total_descuento = Decimal("0")
    subtotal_15 = Decimal("0")
    subtotal_0 = Decimal("0")
    iva_15 = Decimal("0")

    detalles: list[DetalleFactura] = []

    for item in items:
        cantidad = Decimal(str(item.get("cantidad", 1)))
        precio = Decimal(str(item.get("precio_unitario", 0)))
        descuento = Decimal(str(item.get("descuento", 0)))
        aplica_iva = item.get("aplica_iva", True)
        porcentaje_iva = Decimal(str(item.get("porcentaje_iva", 15)))

        precio_total = (cantidad * precio) - descuento
        subtotal_sin_impuestos += precio_total
        total_descuento += descuento

        if aplica_iva and porcentaje_iva > 0:
            subtotal_15 += precio_total
            valor_iva = precio_total * (porcentaje_iva / Decimal("100"))
            iva_15 += valor_iva
            codigo_porcentaje = CodigoPorcentajeIVA.IVA_15
            tarifa = porcentaje_iva
        else:
            subtotal_0 += precio_total
            valor_iva = Decimal("0")
            codigo_porcentaje = CodigoPorcentajeIVA.IVA_0
            tarifa = Decimal("0")

        impuestos = [
            Impuesto(
                codigo=CodigoImpuesto.IVA,
                codigo_porcentaje=codigo_porcentaje,
                tarifa=tarifa,
                base_imponible=precio_total,
                valor=valor_iva.quantize(Decimal("0.01"))
            )
        ]

        detalles.append(DetalleFactura(
            codigo_principal=item.get("codigo"),
            descripcion=item.get("descripcion", "Servicio"),
            cantidad=cantidad,
            precio_unitario=precio,
            descuento=descuento,
            precio_total_sin_impuesto=precio_total,
            impuestos=impuestos
        ))

    # Total con impuestos
    total_con_impuestos: list[TotalImpuesto] = []

    if subtotal_15 > 0:
        total_con_impuestos.append(TotalImpuesto(
            codigo=CodigoImpuesto.IVA,
            codigo_porcentaje=CodigoPorcentajeIVA.IVA_15,
            base_imponible=subtotal_15,
            tarifa=Decimal("15"),
            valor=iva_15.quantize(Decimal("0.01"))
        ))

    if subtotal_0 > 0:
        total_con_impuestos.append(TotalImpuesto(
            codigo=CodigoImpuesto.IVA,
            codigo_porcentaje=CodigoPorcentajeIVA.IVA_0,
            base_imponible=subtotal_0,
            tarifa=Decimal("0"),
            valor=Decimal("0")
        ))

    importe_total = subtotal_sin_impuestos + iva_15

    # Crear modelos
    info_tributaria = InfoTributaria(
        ambiente=ambiente,
        tipo_emision="1",
        razon_social=razon_social,
        nombre_comercial=nombre_comercial,
        ruc=ruc,
        clave_acceso=clave_acceso,
        cod_doc="01",
        estab=establecimiento,
        pto_emi=punto_emision,
        secuencial=str(secuencial).zfill(9),
        dir_matriz=direccion_matriz
    )

    info_factura = InfoFactura(
        fecha_emision=fecha_emision,
        obligado_contabilidad=obligado_contabilidad,
        contribuyente_especial=contribuyente_especial,
        tipo_identificacion_comprador=cliente_tipo_id,
        razon_social_comprador=cliente_razon_social,
        identificacion_comprador=cliente_identificacion,
        direccion_comprador=cliente_direccion,
        total_sin_impuestos=subtotal_sin_impuestos,
        total_descuento=total_descuento,
        total_con_impuestos=total_con_impuestos,
        propina=Decimal("0"),
        importe_total=importe_total,
        pagos=[Pago(forma_pago=forma_pago, total=importe_total)]
    )

    # Agregar email a info adicional
    info_adicional_final = info_adicional or {}
    if cliente_email:
        info_adicional_final["Email"] = cliente_email

    factura = Factura(
        info_tributaria=info_tributaria,
        info_factura=info_factura,
        detalles=detalles,
        info_adicional=info_adicional_final if info_adicional_final else None
    )

    # Construir XML
    builder = XMLBuilder()
    return builder.build_factura(factura)


def crear_nota_credito_xml(
    # Info Tributaria
    ruc: str,
    razon_social: str,
    direccion_matriz: str,
    ambiente: str,
    establecimiento: str,
    punto_emision: str,
    secuencial: int,
    clave_acceso: str,
    nombre_comercial: str | None = None,
    # Info Nota de Crédito
    fecha_emision: date | None = None,
    cliente_tipo_id: TipoIdentificacion = TipoIdentificacion.CONSUMIDOR_FINAL,
    cliente_identificacion: str = "9999999999999",
    cliente_razon_social: str = "CONSUMIDOR FINAL",
    obligado_contabilidad: str = "SI",
    # Documento modificado
    cod_doc_modificado: str = "01",
    num_doc_modificado: str = "",
    fecha_emision_doc_sustento: date | None = None,
    motivo: str = "Anulacion por duplicidad de factura",
    # Items
    items: list[dict[str, Any]] | None = None,
    # Adicional
    info_adicional: dict[str, str] | None = None,
) -> str:
    """
    Función helper para crear el XML de una nota de crédito.

    Args:
        ruc: RUC del emisor
        razon_social: Razón social del emisor
        direccion_matriz: Dirección de la matriz
        ambiente: '1' para pruebas, '2' para producción
        establecimiento: Código de establecimiento
        punto_emision: Código de punto de emisión
        secuencial: Número secuencial de la NC
        clave_acceso: Clave de acceso de 49 dígitos
        nombre_comercial: Nombre comercial (opcional)
        fecha_emision: Fecha de emisión (default: hoy)
        cliente_tipo_id: Tipo de identificación del cliente
        cliente_identificacion: Número de identificación
        cliente_razon_social: Razón social del cliente
        obligado_contabilidad: 'SI' o 'NO'
        cod_doc_modificado: Código del documento modificado ('01' factura)
        num_doc_modificado: Número del documento (ej: '001-001-000000002')
        fecha_emision_doc_sustento: Fecha de emisión del doc sustento
        motivo: Motivo de la nota de crédito
        items: Lista de items (misma estructura que factura)
        info_adicional: Información adicional

    Returns:
        String XML del documento sin firmar
    """
    from datetime import date as date_type

    if fecha_emision is None:
        fecha_emision = date_type.today()
    if fecha_emision_doc_sustento is None:
        fecha_emision_doc_sustento = fecha_emision
    if items is None:
        items = []

    # Calcular totales (misma lógica que factura)
    subtotal_sin_impuestos = Decimal("0")
    subtotal_15 = Decimal("0")
    iva_15 = Decimal("0")

    detalles: list[DetalleFactura] = []

    for item in items:
        cantidad = Decimal(str(item.get("cantidad", 1)))
        precio = Decimal(str(item.get("precio_unitario", 0)))
        descuento = Decimal(str(item.get("descuento", 0)))
        aplica_iva = item.get("aplica_iva", True)
        porcentaje_iva = Decimal(str(item.get("porcentaje_iva", 15)))

        precio_total = (cantidad * precio) - descuento
        subtotal_sin_impuestos += precio_total

        if aplica_iva and porcentaje_iva > 0:
            subtotal_15 += precio_total
            valor_iva = precio_total * (porcentaje_iva / Decimal("100"))
            iva_15 += valor_iva
            codigo_porcentaje = CodigoPorcentajeIVA.IVA_15
            tarifa = porcentaje_iva
        else:
            valor_iva = Decimal("0")
            codigo_porcentaje = CodigoPorcentajeIVA.IVA_0
            tarifa = Decimal("0")

        impuestos = [
            Impuesto(
                codigo=CodigoImpuesto.IVA,
                codigo_porcentaje=codigo_porcentaje,
                tarifa=tarifa,
                base_imponible=precio_total,
                valor=valor_iva.quantize(Decimal("0.01"))
            )
        ]

        detalles.append(DetalleFactura(
            codigo_principal=item.get("codigo"),
            descripcion=item.get("descripcion", "Servicio"),
            cantidad=cantidad,
            precio_unitario=precio,
            descuento=descuento,
            precio_total_sin_impuesto=precio_total,
            impuestos=impuestos
        ))

    # Total con impuestos
    total_con_impuestos: list[TotalImpuesto] = []
    if subtotal_15 > 0:
        total_con_impuestos.append(TotalImpuesto(
            codigo=CodigoImpuesto.IVA,
            codigo_porcentaje=CodigoPorcentajeIVA.IVA_15,
            base_imponible=subtotal_15,
            tarifa=Decimal("15"),
            valor=iva_15.quantize(Decimal("0.01"))
        ))

    valor_modificacion = subtotal_sin_impuestos + iva_15

    # Crear modelos
    info_tributaria = InfoTributaria(
        ambiente=ambiente,
        tipo_emision="1",
        razon_social=razon_social,
        nombre_comercial=nombre_comercial,
        ruc=ruc,
        clave_acceso=clave_acceso,
        cod_doc="04",
        estab=establecimiento,
        pto_emi=punto_emision,
        secuencial=str(secuencial).zfill(9),
        dir_matriz=direccion_matriz
    )

    info_nc = InfoNotaCredito(
        fecha_emision=fecha_emision,
        tipo_identificacion_comprador=cliente_tipo_id,
        razon_social_comprador=cliente_razon_social,
        identificacion_comprador=cliente_identificacion,
        obligado_contabilidad=obligado_contabilidad,
        cod_doc_modificado=cod_doc_modificado,
        num_doc_modificado=num_doc_modificado,
        fecha_emision_doc_sustento=fecha_emision_doc_sustento,
        total_sin_impuestos=subtotal_sin_impuestos,
        valor_modificacion=valor_modificacion,
        total_con_impuestos=total_con_impuestos,
        motivo=motivo,
    )

    nc = NotaCredito(
        info_tributaria=info_tributaria,
        info_nota_credito=info_nc,
        detalles=detalles,
        info_adicional=info_adicional,
    )

    builder = XMLBuilder()
    return builder.build_nota_credito(nc)
