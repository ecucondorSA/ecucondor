"""
ECUCONDOR - Parser de Facturas XML del SRI
Parsea facturas electrónicas descargadas del portal del SRI.
"""

import re
from datetime import datetime
from decimal import Decimal
from typing import Optional
from xml.etree import ElementTree as ET

import structlog

logger = structlog.get_logger(__name__)


class ParserFacturaXML:
    """
    Parser para facturas electrónicas XML del SRI Ecuador.
    
    Formatos soportados:
    - XML de autorización (con tag <autorizacion>)
    - XML de comprobante directo (con tag <factura>)
    """

    # Códigos de IVA del SRI
    CODIGOS_IVA = {
        '0': 'gravado_0',      # 0%
        '2': 'gravado_12',     # 12% (antiguo)
        '3': 'gravado_14',     # 14% (antiguo)
        '4': 'gravado_15',     # 15% (actual)
        '6': 'no_objeto',      # No objeto de IVA
        '7': 'exento',         # Exento de IVA
    }

    def parse(self, xml_content: str) -> Optional[dict]:
        """
        Parsea el contenido XML de una factura.
        
        Args:
            xml_content: String con el contenido XML
            
        Returns:
            Diccionario con los datos de la factura o None si falla
        """
        try:
            # Limpiar BOM y caracteres especiales
            xml_content = xml_content.strip()
            if xml_content.startswith('\ufeff'):
                xml_content = xml_content[1:]

            root = ET.fromstring(xml_content)

            # Detectar formato
            if root.tag == 'autorizacion':
                return self._parse_autorizacion(root)
            elif root.tag == 'factura':
                return self._parse_factura(root)
            elif root.tag == 'comprobante':
                # Buscar factura dentro
                factura = root.find('.//factura')
                if factura is not None:
                    return self._parse_factura(factura)
            else:
                # Intentar buscar factura en cualquier parte
                factura = root.find('.//factura')
                if factura is not None:
                    return self._parse_factura(factura)

            logger.warning(f"Formato XML no reconocido: {root.tag}")
            return None

        except ET.ParseError as e:
            logger.error(f"Error parseando XML: {e}")
            return None
        except Exception as e:
            logger.error(f"Error inesperado parseando XML: {e}", exc_info=True)
            return None

    def _parse_autorizacion(self, root: ET.Element) -> Optional[dict]:
        """Parsea XML con formato de autorización."""
        try:
            # Extraer datos de autorización
            estado = self._get_text(root, 'estado')
            numero_autorizacion = self._get_text(root, 'numeroAutorizacion')
            fecha_autorizacion = self._get_text(root, 'fechaAutorizacion')

            # El comprobante puede estar como texto CDATA
            comprobante_text = self._get_text(root, 'comprobante')

            if comprobante_text:
                # Parsear el comprobante interno
                try:
                    comprobante_root = ET.fromstring(comprobante_text)
                    data = self._parse_factura(comprobante_root)
                except:
                    # Si falla, buscar factura directamente
                    factura = root.find('.//factura')
                    if factura is not None:
                        data = self._parse_factura(factura)
                    else:
                        return None
            else:
                # Buscar factura directamente
                factura = root.find('.//factura')
                if factura is not None:
                    data = self._parse_factura(factura)
                else:
                    return None

            if data:
                data['estado_autorizacion'] = estado
                data['numero_autorizacion'] = numero_autorizacion
                data['fecha_autorizacion'] = fecha_autorizacion

            return data

        except Exception as e:
            logger.error(f"Error parseando autorización: {e}")
            return None

    def _parse_factura(self, factura: ET.Element) -> Optional[dict]:
        """Parsea el elemento factura."""
        try:
            # Info Tributaria (emisor)
            info_trib = factura.find('infoTributaria')
            if info_trib is None:
                logger.error("No se encontró infoTributaria")
                return None

            ruc = self._get_text(info_trib, 'ruc')
            razon_social = self._get_text(info_trib, 'razonSocial')
            nombre_comercial = self._get_text(info_trib, 'nombreComercial')
            establecimiento = self._get_text(info_trib, 'estab')
            punto_emision = self._get_text(info_trib, 'ptoEmi')
            secuencial = self._get_text(info_trib, 'secuencial')
            clave_acceso = self._get_text(info_trib, 'claveAcceso')
            tipo_comprobante = self._get_text(info_trib, 'codDoc') or '01'

            # Info Factura
            info_factura = factura.find('infoFactura')
            if info_factura is None:
                logger.error("No se encontró infoFactura")
                return None

            fecha_emision_str = self._get_text(info_factura, 'fechaEmision')
            fecha_emision = self._parse_fecha(fecha_emision_str)

            # Montos
            total_sin_impuestos = self._get_decimal(info_factura, 'totalSinImpuestos')
            total_descuento = self._get_decimal(info_factura, 'totalDescuento')
            propina = self._get_decimal(info_factura, 'propina')
            importe_total = self._get_decimal(info_factura, 'importeTotal')

            # Impuestos (desglose de IVA)
            subtotal_15 = Decimal('0')
            subtotal_12 = Decimal('0')
            subtotal_0 = Decimal('0')
            subtotal_no_objeto = Decimal('0')
            subtotal_exento = Decimal('0')
            total_iva = Decimal('0')

            total_con_impuestos = info_factura.find('totalConImpuestos')
            if total_con_impuestos is not None:
                for impuesto in total_con_impuestos.findall('totalImpuesto'):
                    codigo = self._get_text(impuesto, 'codigo')
                    codigo_porcentaje = self._get_text(impuesto, 'codigoPorcentaje')
                    base_imponible = self._get_decimal(impuesto, 'baseImponible')
                    valor = self._get_decimal(impuesto, 'valor')

                    if codigo == '2':  # IVA
                        if codigo_porcentaje == '0':
                            subtotal_0 += base_imponible
                        elif codigo_porcentaje in ('2', '3'):  # 12% o 14%
                            subtotal_12 += base_imponible
                        elif codigo_porcentaje == '4':  # 15%
                            subtotal_15 += base_imponible
                        elif codigo_porcentaje == '6':
                            subtotal_no_objeto += base_imponible
                        elif codigo_porcentaje == '7':
                            subtotal_exento += base_imponible

                        total_iva += valor

            # Si no hay desglose, asumir todo gravado 15%
            if subtotal_15 == 0 and subtotal_12 == 0 and subtotal_0 == 0:
                if total_iva > 0:
                    # Calcular base del IVA
                    subtotal_15 = total_sin_impuestos
                else:
                    subtotal_0 = total_sin_impuestos

            # Combinar 12% y 15% (para facturas antiguas)
            subtotal_gravado = subtotal_15 + subtotal_12

            # Detalles
            detalles = []
            detalles_elem = factura.find('detalles')
            if detalles_elem is not None:
                for detalle in detalles_elem.findall('detalle'):
                    item = {
                        'codigo': self._get_text(detalle, 'codigoPrincipal') or self._get_text(detalle, 'codigoInterno'),
                        'descripcion': self._get_text(detalle, 'descripcion'),
                        'cantidad': float(self._get_decimal(detalle, 'cantidad')),
                        'precio_unitario': float(self._get_decimal(detalle, 'precioUnitario')),
                        'descuento': float(self._get_decimal(detalle, 'descuento')),
                        'precio_total': float(self._get_decimal(detalle, 'precioTotalSinImpuesto')),
                    }

                    # IVA del detalle
                    impuestos_det = detalle.find('impuestos')
                    if impuestos_det is not None:
                        for imp in impuestos_det.findall('impuesto'):
                            codigo_porc = self._get_text(imp, 'codigoPorcentaje')
                            tarifa = self._get_decimal(imp, 'tarifa')
                            valor_iva = self._get_decimal(imp, 'valor')

                            item['tipo_iva'] = self.CODIGOS_IVA.get(codigo_porc, 'gravado_15')
                            item['tarifa_iva'] = float(tarifa)
                            item['valor_iva'] = float(valor_iva)

                    detalles.append(item)

            return {
                'tipo_comprobante': tipo_comprobante,
                'proveedor_ruc': ruc,
                'proveedor_razon_social': razon_social,
                'proveedor_nombre_comercial': nombre_comercial,
                'establecimiento': establecimiento,
                'punto_emision': punto_emision,
                'secuencial': secuencial,
                'clave_acceso': clave_acceso,
                'fecha_emision': fecha_emision,
                'subtotal': float(total_sin_impuestos),
                'subtotal_15': float(subtotal_gravado),
                'subtotal_0': float(subtotal_0),
                'subtotal_no_objeto': float(subtotal_no_objeto),
                'subtotal_exento': float(subtotal_exento),
                'descuento': float(total_descuento),
                'iva': float(total_iva),
                'propina': float(propina),
                'total': float(importe_total),
                'detalles': detalles,
            }

        except Exception as e:
            logger.error(f"Error parseando factura: {e}", exc_info=True)
            return None

    def _get_text(self, element: ET.Element, tag: str) -> str:
        """Obtiene el texto de un subelemento."""
        child = element.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return ''

    def _get_decimal(self, element: ET.Element, tag: str) -> Decimal:
        """Obtiene un valor decimal de un subelemento."""
        text = self._get_text(element, tag)
        if text:
            try:
                return Decimal(text.replace(',', '.'))
            except:
                return Decimal('0')
        return Decimal('0')

    def _parse_fecha(self, fecha_str: str) -> str:
        """Parsea fecha en varios formatos del SRI."""
        if not fecha_str:
            return datetime.now().strftime('%Y-%m-%d')

        formatos = [
            '%d/%m/%Y',
            '%Y-%m-%d',
            '%d-%m-%Y',
            '%Y/%m/%d',
        ]

        for fmt in formatos:
            try:
                dt = datetime.strptime(fecha_str, fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue

        # Último intento con regex
        match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', fecha_str)
        if match:
            dia, mes, anio = match.groups()
            return f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}"

        return datetime.now().strftime('%Y-%m-%d')
