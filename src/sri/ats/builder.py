"""
ECUCONDOR - Constructor de XML para ATS (Anexo Transaccional Simplificado)
Genera el archivo XML según especificaciones del SRI Ecuador.
Incluye validación automática contra el XSD oficial.
"""

from lxml import etree
from decimal import Decimal
from typing import List
from .models import ATS, DetalleVenta, DetalleAnulado, DetalleCompra, PagoExterior, VentaEstablecimiento
from .validator import validar_xml


class ATSBuilder:
    """
    Constructor de archivos XML para el Anexo Transaccional Simplificado.

    Genera XML válido según la ficha técnica del SRI para ser subido
    al portal de declaraciones. Incluye validación XSD automática.
    """

    def build(self, ats: ATS, validar: bool = True) -> str:
        """
        Construye el XML del ATS y lo valida contra el XSD oficial.

        Args:
            ats: Modelo ATS con todos los datos del período
            validar: Si True, valida contra XSD antes de retornar (default: True)

        Returns:
            String con el XML completo

        Raises:
            ValueError: Si el XML no pasa validación XSD
        """
        # Auto-generar ventasEstablecimiento si no fue proporcionado
        if not ats.ventas_establecimiento:
            total_ventas = ats.calcular_total_ventas()
            ats.ventas_establecimiento = [
                VentaEstablecimiento(cod_estab=ats.num_estab_ruc or "001", ventas_estab=total_ventas)
            ]

        # Elemento raíz
        root = etree.Element("iva")

        # Cabecera - Identificación del informante (obligatoria)
        self._add_element(root, "TipoIDInformante", ats.tipo_id_informante)
        self._add_element(root, "IdInformante", ats.id_informante)
        self._add_element(root, "razonSocial", ats.razon_social)
        self._add_element(root, "Anio", str(ats.anio))
        self._add_element(root, "Mes", f"{ats.mes:02d}")

        # Orden estricto según XSD (xsd:sequence):
        # numEstabRuc → totalVentas → codigoOperativo → compras → ventas
        # → ventasEstablecimiento → anulados

        if ats.num_estab_ruc:
            self._add_element(root, "numEstabRuc", ats.num_estab_ruc)

        if hasattr(ats, 'total_ventas') and ats.total_ventas is not None:
            total_ventas = ats.total_ventas
        else:
            total_ventas = ats.calcular_total_ventas() if ats.ventas else Decimal("0.00")

        self._add_element(root, "totalVentas", self._decimal_str(total_ventas))
        self._add_element(root, "codigoOperativo", ats.codigo_operativo)

        if ats.compras:
            self._add_compras(root, ats.compras)

        if ats.ventas:
            self._add_ventas(root, ats.ventas)

        for ve in ats.ventas_establecimiento:
            self._add_ventas_establecimiento(root, ve.cod_estab, ve.ventas_estab)

        if ats.anulados:
            self._add_anulados(root, ats.anulados)

        # Generar XML con declaración ISO-8859-1 (requerido por SRI)
        xml_bytes = etree.tostring(root, encoding="unicode", pretty_print=False)
        xml_str = '<?xml version="1.0" encoding="ISO-8859-1"?>' + xml_bytes + "\n"

        # Validar contra XSD oficial del SRI
        if validar:
            valido, errores = validar_xml(xml_str)
            if not valido:
                raise ValueError(
                    f"ATS XML no pasa validación XSD del SRI:\n" +
                    "\n".join(f"  - {e}" for e in errores)
                )

        return xml_str

    def _add_compras(self, root: etree.Element, compras: List[DetalleCompra]) -> None:
        """Agrega la sección de compras al XML."""
        compras_elem = etree.SubElement(root, "compras")
        
        for c in compras:
            det = etree.SubElement(compras_elem, "detalleCompras")
            
            self._add_element(det, "codSustento", c.cod_sustento)
            self._add_element(det, "tpIdProv", c.tp_id_prov)
            self._add_element(det, "idProv", c.id_prov)
            self._add_element(det, "tipoComprobante", c.tipo_comprobante)
            
            if c.tipo_prov:
                self._add_element(det, "tipoProv", c.tipo_prov)
            if c.deno_prov:
                self._add_element(det, "denoProv", self._limpiar_texto(c.deno_prov))
                
            self._add_element(det, "parteRel", c.parte_relacionada)
            self._add_element(det, "fechaRegistro", c.fecha_registro)
            self._add_element(det, "establecimiento", c.establecimiento)
            self._add_element(det, "puntoEmision", c.punto_emision)
            self._add_element(det, "secuencial", c.secuencial)
            self._add_element(det, "fechaEmision", c.fecha_emision)
            self._add_element(det, "autorizacion", c.autorizacion)
            
            self._add_element(det, "baseNoGraIva", self._decimal_str(c.base_no_grava_iva))
            self._add_element(det, "baseImponible", self._decimal_str(c.base_imponible_0))
            self._add_element(det, "baseImpGrav", self._decimal_str(c.base_imponible_15))
            self._add_element(det, "baseImpExe", self._decimal_str(c.base_exenta))
            
            self._add_element(det, "montoIva", self._decimal_str(c.monto_iva))
            self._add_element(det, "montoIce", self._decimal_str(c.monto_ice))
            
            self._add_element(det, "valRetBien10", self._decimal_str(c.val_ret_bien_10))
            self._add_element(det, "valRetServ20", self._decimal_str(c.val_ret_serv_20))
            self._add_element(det, "valorRetBienes", self._decimal_str(c.valor_ret_bienes))
            self._add_element(det, "valRetServ50", self._decimal_str(c.val_ret_serv_50))
            self._add_element(det, "valorRetServicios", self._decimal_str(c.valor_ret_servicios))
            self._add_element(det, "valRetServ100", self._decimal_str(c.val_ret_serv_100))
            
            self._add_element(det, "totbasesImpobstReemb", self._decimal_str(c.tot_bases_impobst_reemb))
            
            # Pago exterior
            pago = etree.SubElement(det, "pagoExterior")
            self._add_element(pago, "pagoLocExt", c.pago_exterior.pago_loc_ext)
            if c.pago_exterior.pago_loc_ext != "01":
                self._add_element(pago, "tipoRegi", c.pago_exterior.tipo_regim)
                self._add_element(pago, "paisEfecPago", c.pago_exterior.pais_efec_pago)
                self._add_element(pago, "aplicConvDobTrib", c.pago_exterior.aplic_conv_dob_trib)
                self._add_element(pago, "pagExtSujRetNorLeg", c.pago_exterior.pag_ext_suj_ret_nor_leg)
            else:
                self._add_element(pago, "paisEfecPago", "NA")
                self._add_element(pago, "aplicConvDobTrib", "NA")
                self._add_element(pago, "pagExtSujRetNorLeg", "NA")

            # Formas de pago
            if c.formas_pago:
                formas = etree.SubElement(det, "formasDePago")
                for fp in c.formas_pago:
                    self._add_element(formas, "formaPago", fp)

            # Retenciones de AIR (vacío por ahora, se puede expandir)
            # air = etree.SubElement(det, "air")
            # detalle_air = etree.SubElement(air, "detalleAir")
            # self._add_element(detalle_air, "codRetAir", "332") # Ejemplo

    def _add_ventas(self, root: etree.Element, ventas: List[DetalleVenta]) -> None:
        """Agrega la sección de ventas al XML."""
        ventas_elem = etree.SubElement(root, "ventas")
        # Forzar elemento no self-closing cuando está vacío
        if not ventas:
            ventas_elem.text = ""

        for v in ventas:
            det = etree.SubElement(ventas_elem, "detalleVentas")

            # Tipo y número de identificación
            self._add_element(det, "tpIdCliente", v.tipo_id_cliente)
            self._add_element(det, "idCliente", v.id_cliente)

            # Parte relacionada
            self._add_element(det, "parteRelVtas", v.parte_relacionada)

            # Tipo de comprobante y emisión
            self._add_element(det, "tipoComprobante", v.tipo_comprobante)
            self._add_element(det, "tipoEmision", v.tipo_emision)

            # Cantidad de comprobantes
            self._add_element(det, "numeroComprobantes", str(v.numero_comprobantes))

            # Bases imponibles
            self._add_element(det, "baseNoGraIva", self._decimal_str(v.base_no_grava_iva))
            self._add_element(det, "baseImponible", self._decimal_str(v.base_imponible_0))
            self._add_element(det, "baseImpGrav", self._decimal_str(v.base_imponible_15))

            # Impuestos
            self._add_element(det, "montoIva", self._decimal_str(v.monto_iva))
            self._add_element(det, "montoIce", self._decimal_str(v.monto_ice))

            # Retenciones recibidas
            self._add_element(det, "valorRetIva", self._decimal_str(v.valor_ret_iva))
            self._add_element(det, "valorRetRenta", self._decimal_str(v.valor_ret_renta))

            # Formas de pago
            formas = etree.SubElement(det, "formasDePago")
            for fp in v.formas_pago:
                self._add_element(formas, "formaPago", fp)

    def _add_ventas_establecimiento(
        self,
        root: etree.Element,
        cod_estab: str,
        total: Decimal
    ) -> None:
        """Agrega el resumen de ventas por establecimiento."""
        ventas_est = etree.SubElement(root, "ventasEstablecimiento")
        venta_est_item = etree.SubElement(ventas_est, "ventaEst")
        self._add_element(venta_est_item, "codEstab", cod_estab)
        self._add_element(venta_est_item, "ventasEstab", self._decimal_str(total))
        self._add_element(venta_est_item, "ivaComp", "0.00")

    def _add_anulados(self, root: etree.Element, anulados: List[DetalleAnulado]) -> None:
        """Agrega la sección de comprobantes anulados."""
        anulados_elem = etree.SubElement(root, "anulados")

        for a in anulados:
            det = etree.SubElement(anulados_elem, "detalleAnulados")

            self._add_element(det, "tipoComprobante", a.tipo_comprobante)
            self._add_element(det, "establecimiento", a.establecimiento)
            self._add_element(det, "puntoEmision", a.punto_emision)
            self._add_element(det, "secuencialInicio", a.secuencial_inicio)
            self._add_element(det, "secuencialFin", a.secuencial_fin)
            self._add_element(det, "autorizacion", a.autorizacion)

    def _add_element(self, parent: etree.Element, tag: str, text: str) -> etree.Element:
        """Agrega un elemento con texto al padre."""
        elem = etree.SubElement(parent, tag)
        elem.text = str(text) if text is not None else ""
        return elem

    def _decimal_str(self, value: Decimal) -> str:
        """Convierte un Decimal a string con 2 decimales."""
        if value is None:
            return "0.00"
        return f"{value:.2f}"

    def _limpiar_texto(self, texto: str) -> str:
        """Limita longitud del texto. lxml escapa caracteres XML automáticamente."""
        if not texto:
            return ""
        return texto[:300]
