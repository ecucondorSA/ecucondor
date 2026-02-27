"""
ECUCONDOR - Generador de RIDE (Representación Impresa del Documento Electrónico)
Genera PDFs de los comprobantes electrónicos usando WeasyPrint y Jinja2.
"""

import base64
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML, CSS

from src.config.constants import (
    TipoComprobante,
    TipoIdentificacion,
    FormaPago,
)

logger = structlog.get_logger(__name__)

# Directorio de templates
TEMPLATES_DIR = Path(__file__).parent / "templates"


# Mapeos para texto legible
TIPO_IDENTIFICACION_NOMBRES = {
    "04": "RUC",
    "05": "CÉDULA",
    "06": "PASAPORTE",
    "07": "CONSUMIDOR FINAL",
    "08": "EXTERIOR",
}

FORMA_PAGO_NOMBRES = {
    "01": "SIN UTILIZACIÓN DEL SISTEMA FINANCIERO",
    "15": "COMPENSACIÓN DE DEUDAS",
    "16": "TARJETA DE DÉBITO",
    "17": "DINERO ELECTRÓNICO",
    "18": "TARJETA PREPAGO",
    "19": "TARJETA DE CRÉDITO",
    "20": "OTROS CON UTILIZACIÓN DEL SISTEMA FINANCIERO",
    "21": "ENDOSO DE TÍTULOS",
}


class RIDEGenerator:
    """
    Generador de documentos RIDE en formato PDF.

    El RIDE es la representación impresa obligatoria de los
    comprobantes electrónicos del SRI.
    """

    def __init__(self, templates_dir: Path | str | None = None):
        """
        Inicializa el generador de RIDE.

        Args:
            templates_dir: Directorio con los templates Jinja2.
                          Si es None, usa el directorio por defecto.
        """
        self.templates_dir = Path(templates_dir) if templates_dir else TEMPLATES_DIR

        # Configurar Jinja2
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

        # Registrar filtros personalizados
        self.env.filters["formato_monto"] = self._formato_monto
        self.env.filters["formato_fecha"] = self._formato_fecha
        self.env.filters["formato_cantidad"] = self._formato_cantidad

        logger.info("RIDEGenerator inicializado", templates_dir=str(self.templates_dir))

    @staticmethod
    def _formato_monto(valor: Decimal | float | str | None) -> str:
        """Formatea un monto con 2 decimales y separador de miles."""
        if valor is None:
            return "0.00"
        if isinstance(valor, str):
            valor = Decimal(valor)
        return f"{valor:,.2f}"

    @staticmethod
    def _formato_fecha(fecha: date | datetime | str | None, formato: str = "%d/%m/%Y") -> str:
        """Formatea una fecha."""
        if fecha is None:
            return ""
        if isinstance(fecha, str):
            # Intentar parsear diferentes formatos
            for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    fecha = datetime.strptime(fecha, fmt)
                    break
                except ValueError:
                    continue
        if isinstance(fecha, (date, datetime)):
            return fecha.strftime(formato)
        return str(fecha)

    @staticmethod
    def _formato_cantidad(valor: Decimal | float | str | None) -> str:
        """Formatea una cantidad con hasta 6 decimales."""
        if valor is None:
            return "0"
        if isinstance(valor, str):
            valor = Decimal(valor)
        # Eliminar ceros innecesarios a la derecha
        formatted = f"{valor:.6f}".rstrip('0').rstrip('.')
        return formatted

    def generar_factura_pdf(
        self,
        datos: dict[str, Any],
        output_path: str | Path | None = None,
    ) -> bytes:
        """
        Genera el PDF del RIDE de una factura.

        Args:
            datos: Diccionario con los datos de la factura:
                - emisor: dict con datos del emisor
                - comprador: dict con datos del comprador
                - factura: dict con datos de la factura
                - detalles: lista de items
                - totales: dict con totales e impuestos
                - pagos: lista de formas de pago
                - autorizacion: dict con datos de autorización SRI
            output_path: Ruta opcional para guardar el PDF

        Returns:
            Bytes del PDF generado
        """
        try:
            # Preparar contexto para el template
            context = self._preparar_contexto_factura(datos)

            # Renderizar HTML
            template = self.env.get_template("factura_ride.html")
            html_content = template.render(**context)

            # Generar PDF
            pdf_bytes = self._html_to_pdf(html_content)

            # Guardar si se especificó ruta
            if output_path:
                output_path = Path(output_path)
                output_path.write_bytes(pdf_bytes)
                logger.info("PDF guardado", path=str(output_path))

            logger.info(
                "RIDE generado exitosamente",
                tipo="factura",
                numero=context.get("numero_comprobante"),
                size_kb=len(pdf_bytes) / 1024,
            )

            return pdf_bytes

        except Exception as e:
            logger.error("Error generando RIDE", error=str(e))
            raise

    def _preparar_contexto_factura(self, datos: dict[str, Any]) -> dict[str, Any]:
        """Prepara el contexto para el template de factura."""
        emisor = datos.get("emisor", {})
        comprador = datos.get("comprador", {})
        factura = datos.get("factura", {})
        detalles = datos.get("detalles", [])
        totales = datos.get("totales", {})
        pagos = datos.get("pagos", [])
        autorizacion = datos.get("autorizacion", {})
        info_adicional = datos.get("info_adicional", {})

        # Generar código de barras (simulado, en producción usar library)
        clave_acceso = autorizacion.get("clave_acceso", "")

        return {
            # Emisor
            "emisor_ruc": emisor.get("ruc", ""),
            "emisor_razon_social": emisor.get("razon_social", ""),
            "emisor_nombre_comercial": emisor.get("nombre_comercial", ""),
            "emisor_direccion": emisor.get("direccion_matriz", ""),
            "emisor_obligado_contabilidad": emisor.get("obligado_contabilidad", "SI"),
            "emisor_contribuyente_especial": emisor.get("contribuyente_especial"),
            "emisor_agente_retencion": emisor.get("agente_retencion"),

            # Comprobante
            "tipo_comprobante": "FACTURA",
            "numero_comprobante": factura.get("numero", "001-001-000000001"),
            "ambiente": "PRUEBAS" if autorizacion.get("ambiente") == "1" else "PRODUCCIÓN",
            "emision": "NORMAL",

            # Autorización
            "clave_acceso": clave_acceso,
            "numero_autorizacion": autorizacion.get("numero_autorizacion", clave_acceso),
            "fecha_autorizacion": autorizacion.get("fecha_autorizacion"),

            # Comprador
            "comprador_tipo_id": TIPO_IDENTIFICACION_NOMBRES.get(
                comprador.get("tipo_identificacion", "05"), "CÉDULA"
            ),
            "comprador_identificacion": comprador.get("identificacion", ""),
            "comprador_razon_social": comprador.get("razon_social", ""),
            "comprador_direccion": comprador.get("direccion", ""),
            "comprador_email": comprador.get("email", ""),
            "comprador_telefono": comprador.get("telefono", ""),

            # Factura
            "fecha_emision": factura.get("fecha_emision"),
            "guia_remision": factura.get("guia_remision"),

            # Detalles
            "detalles": [
                {
                    "codigo": d.get("codigo", ""),
                    "descripcion": d.get("descripcion", ""),
                    "cantidad": d.get("cantidad", 0),
                    "precio_unitario": d.get("precio_unitario", 0),
                    "descuento": d.get("descuento", 0),
                    "precio_total": d.get("precio_total_sin_impuesto", 0),
                }
                for d in detalles
            ],

            # Totales
            "subtotal_15": totales.get("subtotal_15", Decimal("0")),
            "subtotal_0": totales.get("subtotal_0", Decimal("0")),
            "subtotal_no_objeto": totales.get("subtotal_no_objeto", Decimal("0")),
            "subtotal_exento": totales.get("subtotal_exento", Decimal("0")),
            "subtotal_sin_impuestos": totales.get("subtotal_sin_impuestos", Decimal("0")),
            "total_descuento": totales.get("total_descuento", Decimal("0")),
            "iva_15": totales.get("iva", Decimal("0")),
            "ice": totales.get("ice", Decimal("0")),
            "propina": totales.get("propina", Decimal("0")),
            "importe_total": totales.get("importe_total", Decimal("0")),

            # Pagos
            "pagos": [
                {
                    "forma_pago": FORMA_PAGO_NOMBRES.get(p.get("forma_pago", "20"), "OTROS"),
                    "total": p.get("total", 0),
                    "plazo": p.get("plazo"),
                    "unidad_tiempo": p.get("unidad_tiempo"),
                }
                for p in pagos
            ],

            # Info adicional
            "info_adicional": info_adicional,

            # Fecha de generación
            "fecha_generacion": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        }

    def _html_to_pdf(self, html_content: str) -> bytes:
        """Convierte HTML a PDF usando WeasyPrint."""
        # CSS base para el RIDE
        css = CSS(string="""
            @page {
                size: A4;
                margin: 1cm;
            }
            body {
                font-family: 'DejaVu Sans', Arial, sans-serif;
                font-size: 10pt;
                line-height: 1.3;
            }
            table {
                width: 100%;
                border-collapse: collapse;
            }
            th, td {
                padding: 4px 6px;
                text-align: left;
            }
            .text-right {
                text-align: right;
            }
            .text-center {
                text-align: center;
            }
            .border {
                border: 1px solid #000;
            }
            .border-bottom {
                border-bottom: 1px solid #000;
            }
            .bold {
                font-weight: bold;
            }
            .small {
                font-size: 8pt;
            }
            .header {
                margin-bottom: 10px;
            }
            .clave-acceso {
                font-family: monospace;
                font-size: 9pt;
                letter-spacing: 1px;
            }
        """)

        html = HTML(string=html_content, base_url=str(self.templates_dir))
        pdf_bytes = html.write_pdf(stylesheets=[css])

        return pdf_bytes

    def generar_nota_credito_pdf(
        self,
        datos: dict[str, Any],
        output_path: str | Path | None = None,
    ) -> bytes:
        """Genera el PDF del RIDE de una nota de crédito."""
        # Similar a factura pero con template diferente
        context = self._preparar_contexto_factura(datos)
        context["tipo_comprobante"] = "NOTA DE CRÉDITO"
        context["documento_modificado"] = datos.get("documento_modificado", {})
        context["motivo"] = datos.get("motivo", "")

        template = self.env.get_template("nota_credito_ride.html")
        html_content = template.render(**context)

        pdf_bytes = self._html_to_pdf(html_content)

        if output_path:
            Path(output_path).write_bytes(pdf_bytes)

        return pdf_bytes

    def generar_retencion_pdf(
        self,
        datos: dict[str, Any],
        output_path: str | Path | None = None,
    ) -> bytes:
        """Genera el PDF del RIDE de un comprobante de retención."""
        context = self._preparar_contexto_retencion(datos)

        template = self.env.get_template("retencion_ride.html")
        html_content = template.render(**context)

        pdf_bytes = self._html_to_pdf(html_content)

        if output_path:
            Path(output_path).write_bytes(pdf_bytes)

        return pdf_bytes

    def _preparar_contexto_retencion(self, datos: dict[str, Any]) -> dict[str, Any]:
        """Prepara el contexto para el template de retención."""
        emisor = datos.get("emisor", {})
        sujeto = datos.get("sujeto_retenido", {})
        retencion = datos.get("retencion", {})
        impuestos = datos.get("impuestos", [])
        autorizacion = datos.get("autorizacion", {})

        return {
            # Emisor (Agente de retención)
            "emisor_ruc": emisor.get("ruc", ""),
            "emisor_razon_social": emisor.get("razon_social", ""),
            "emisor_direccion": emisor.get("direccion_matriz", ""),
            "emisor_contribuyente_especial": emisor.get("contribuyente_especial"),
            "emisor_obligado_contabilidad": emisor.get("obligado_contabilidad", "SI"),

            # Comprobante
            "tipo_comprobante": "COMPROBANTE DE RETENCIÓN",
            "numero_comprobante": retencion.get("numero", "001-001-000000001"),
            "ambiente": "PRUEBAS" if autorizacion.get("ambiente") == "1" else "PRODUCCIÓN",

            # Autorización
            "clave_acceso": autorizacion.get("clave_acceso", ""),
            "numero_autorizacion": autorizacion.get("numero_autorizacion", ""),
            "fecha_autorizacion": autorizacion.get("fecha_autorizacion"),

            # Sujeto retenido
            "sujeto_tipo_id": TIPO_IDENTIFICACION_NOMBRES.get(
                sujeto.get("tipo_identificacion", "04"), "RUC"
            ),
            "sujeto_identificacion": sujeto.get("identificacion", ""),
            "sujeto_razon_social": sujeto.get("razon_social", ""),

            # Período fiscal
            "periodo_fiscal": retencion.get("periodo_fiscal", ""),
            "fecha_emision": retencion.get("fecha_emision"),

            # Impuestos retenidos
            "impuestos": [
                {
                    "tipo_documento": imp.get("tipo_documento", ""),
                    "numero_documento": imp.get("numero_documento", ""),
                    "fecha_documento": imp.get("fecha_emision_documento"),
                    "codigo": imp.get("codigo_retencion", ""),
                    "tipo": imp.get("tipo_retencion", ""),  # IR o IVA
                    "base_imponible": imp.get("base_imponible", 0),
                    "porcentaje": imp.get("porcentaje", 0),
                    "valor_retenido": imp.get("valor_retenido", 0),
                }
                for imp in impuestos
            ],

            # Total
            "total_retenido": sum(
                Decimal(str(imp.get("valor_retenido", 0))) for imp in impuestos
            ),

            # Fecha generación
            "fecha_generacion": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        }


def generar_ride_factura(datos: dict[str, Any], output_path: str | None = None) -> bytes:
    """
    Función helper para generar un RIDE de factura.

    Args:
        datos: Datos de la factura
        output_path: Ruta opcional para guardar el PDF

    Returns:
        Bytes del PDF
    """
    generator = RIDEGenerator()
    return generator.generar_factura_pdf(datos, output_path)
