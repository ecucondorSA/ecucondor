"""
ECUCONDOR - Parser Banco Pichincha
Parser específico para extractos del Banco Pichincha (Ecuador).

Formatos soportados:
- CSV descargado de Banca Web Empresas
- CSV descargado de Banca Web Personas
- Excel de movimientos históricos
"""

import re
from decimal import Decimal

import pandas as pd
import structlog

from src.ingestor.models import (
    BancoEcuador,
    OrigenTransaccion,
    TipoTransaccion,
    TransaccionBancaria,
)
from src.ingestor.parsers.base import BankParser

logger = structlog.get_logger(__name__)


class PichinchaParser(BankParser):
    """
    Parser para extractos del Banco Pichincha.

    El Banco Pichincha usa varios formatos dependiendo del tipo de cuenta
    y la interfaz de descarga. Este parser intenta detectar automáticamente
    el formato.

    Formatos conocidos:
    1. Empresas: FECHA, DOCUMENTO, OFICINA, DESCRIPCION, DEBITOS, CREDITOS, SALDO
    2. Personas: Fecha, Descripción, Número Documento, Débito, Crédito, Saldo
    3. Histórico: fecha_movimiento, descripcion, referencia, valor, saldo
    """

    banco = BancoEcuador.PICHINCHA
    encoding = "utf-8"  # También puede ser latin-1
    delimiter = ","
    skip_rows = 0

    # Patrones de columnas para diferentes formatos
    COLUMN_PATTERNS = {
        "empresas": {
            "fecha": ["FECHA", "Fecha"],
            "documento": ["DOCUMENTO", "Documento", "NÚMERO DOCUMENTO", "Número Documento"],
            "oficina": ["OFICINA", "Oficina"],
            "descripcion": ["DESCRIPCION", "Descripción", "DETALLE", "Detalle"],
            "debito": ["DEBITOS", "Débitos", "DEBITO", "Débito"],
            "credito": ["CREDITOS", "Créditos", "CREDITO", "Crédito"],
            "saldo": ["SALDO", "Saldo"],
        },
        "historico": {
            "fecha": ["fecha_movimiento", "fecha"],
            "descripcion": ["descripcion"],
            "referencia": ["referencia", "ref"],
            "valor": ["valor", "monto"],
            "saldo": ["saldo"],
        },
    }

    # Patrones para extraer información de descripciones
    DESCRIPCION_PATTERNS = {
        # Transferencias interbancarias
        "transferencia_in": re.compile(
            r"(?:TRANSF|TRANSFER|TRF).*?(?:DE|FROM)\s+(.+?)(?:\s+RUC|\s+CI|\s+CTA|$)",
            re.IGNORECASE
        ),
        "transferencia_out": re.compile(
            r"(?:TRANSF|TRANSFER|TRF).*?(?:A|TO|PARA)\s+(.+?)(?:\s+RUC|\s+CI|\s+CTA|$)",
            re.IGNORECASE
        ),
        # Número de cuenta
        "cuenta": re.compile(r"CTA\.?\s*[:#]?\s*(\d{10,20})", re.IGNORECASE),
        # RUC o cédula
        "identificacion": re.compile(
            r"(?:RUC|CI|CED|CEDULA)[:\s#]*(\d{10,13})",
            re.IGNORECASE
        ),
        # Referencia de transacción
        "referencia": re.compile(
            r"(?:REF|REFERENCIA|COMP|COMPROBANTE)[.:\s#]*(\w+)",
            re.IGNORECASE
        ),
        # Cheque
        "cheque": re.compile(r"(?:CHEQUE?|CH)[.:\s#]*(\d+)", re.IGNORECASE),
    }

    def detect_columns(self, df: pd.DataFrame) -> dict[str, str]:
        """
        Detecta automáticamente el mapeo de columnas.

        Args:
            df: DataFrame con datos del extracto

        Returns:
            Diccionario con mapeo de columnas
        """
        columns = {col.strip().upper(): col for col in df.columns}
        mapping = {}

        # Detectar fecha
        for pattern in ["FECHA", "FECHA_MOVIMIENTO", "DATE"]:
            for col_upper, col_orig in columns.items():
                if pattern in col_upper:
                    mapping["fecha"] = col_orig
                    break
            if "fecha" in mapping:
                break

        # Detectar descripción
        for pattern in ["DESCRIPCION", "DETALLE", "CONCEPTO", "DESCRIPTION"]:
            for col_upper, col_orig in columns.items():
                if pattern in col_upper:
                    mapping["descripcion"] = col_orig
                    break
            if "descripcion" in mapping:
                break

        # Detectar débito
        for pattern in ["DEBITO", "DEBITOS", "CARGO", "WITHDRAWAL"]:
            for col_upper, col_orig in columns.items():
                if pattern in col_upper:
                    mapping["debito"] = col_orig
                    break
            if "debito" in mapping:
                break

        # Detectar crédito
        for pattern in ["CREDITO", "CREDITOS", "ABONO", "DEPOSIT"]:
            for col_upper, col_orig in columns.items():
                if pattern in col_upper:
                    mapping["credito"] = col_orig
                    break
            if "credito" in mapping:
                break

        # Detectar saldo
        for pattern in ["SALDO", "BALANCE"]:
            for col_upper, col_orig in columns.items():
                if pattern in col_upper:
                    mapping["saldo"] = col_orig
                    break
            if "saldo" in mapping:
                break

        # Detectar documento/referencia
        for pattern in ["DOCUMENTO", "NUMERO", "REFERENCIA", "REF"]:
            for col_upper, col_orig in columns.items():
                if pattern in col_upper:
                    mapping["documento"] = col_orig
                    break
            if "documento" in mapping:
                break

        # Detectar oficina (específico de Pichincha Empresas)
        for pattern in ["OFICINA", "SUCURSAL", "AGENCIA"]:
            for col_upper, col_orig in columns.items():
                if pattern in col_upper:
                    mapping["oficina"] = col_orig
                    break
            if "oficina" in mapping:
                break

        # Si hay columna "valor" única (formato simplificado)
        if "VALOR" in columns and "debito" not in mapping:
            mapping["valor"] = columns["VALOR"]

        logger.debug(
            "Columnas detectadas",
            mapping=mapping,
            columnas_archivo=list(df.columns),
        )

        return mapping

    def parse_row(self, row: pd.Series, linea: int) -> TransaccionBancaria | None:
        """
        Parsea una fila del extracto Pichincha.

        Args:
            row: Fila de pandas
            linea: Número de línea

        Returns:
            Transacción parseada o None
        """
        # Obtener mapeo de columnas si no existe
        if not hasattr(self, "_column_map"):
            self._column_map = self.detect_columns(row.to_frame().T)

        col_map = self._column_map

        # Parsear fecha
        fecha_col = col_map.get("fecha")
        if not fecha_col:
            self._errores.append(f"Línea {linea}: No se encontró columna de fecha")
            return None

        fecha = self.parse_date(row.get(fecha_col))
        if not fecha:
            return None

        # Parsear descripción
        desc_col = col_map.get("descripcion")
        descripcion = str(row.get(desc_col, "")).strip() if desc_col else ""

        if not descripcion:
            self._advertencias.append(f"Línea {linea}: Descripción vacía")
            descripcion = "SIN DESCRIPCION"

        # Parsear montos
        if "valor" in col_map:
            # Formato de valor único (positivo=crédito, negativo=débito)
            valor = self.parse_amount(row.get(col_map["valor"]))
            if valor is None:
                return None

            if valor >= 0:
                tipo = TipoTransaccion.CREDITO
                monto = valor
            else:
                tipo = TipoTransaccion.DEBITO
                monto = abs(valor)
        else:
            # Formato de columnas separadas
            debito = self.parse_amount(row.get(col_map.get("debito")))
            credito = self.parse_amount(row.get(col_map.get("credito")))
            tipo, monto = self.detect_transaction_type(credito, debito)

        if monto == Decimal("0"):
            self._advertencias.append(f"Línea {linea}: Monto cero, omitida")
            return None

        # Parsear saldo
        saldo = None
        if "saldo" in col_map:
            saldo = self.parse_amount(row.get(col_map["saldo"]))

        # Obtener referencia/documento
        referencia = None
        if "documento" in col_map:
            doc = row.get(col_map["documento"])
            if pd.notna(doc):
                referencia = str(doc).strip()

        # Extraer información adicional de la descripción
        info_extra = self._extraer_info_descripcion(descripcion)

        # Generar hash único
        hash_unico = self.generate_hash(fecha, monto, descripcion, referencia)

        # Detectar origen
        origen = self.detect_origen(descripcion)

        # Crear transacción
        return TransaccionBancaria(
            hash_unico=hash_unico,
            banco=self.banco,
            cuenta_bancaria=self.cuenta_bancaria,
            fecha=fecha,
            tipo=tipo,
            origen=origen,
            monto=monto,
            saldo=saldo,
            descripcion_original=descripcion,
            referencia=referencia or info_extra.get("referencia"),
            numero_documento=referencia,
            contraparte_nombre=info_extra.get("contraparte"),
            contraparte_identificacion=info_extra.get("identificacion"),
            contraparte_cuenta=info_extra.get("cuenta"),
            datos_originales=row.to_dict(),
        )

    def _extraer_info_descripcion(self, descripcion: str) -> dict[str, str | None]:
        """
        Extrae información estructurada de la descripción.

        Args:
            descripcion: Texto de la descripción

        Returns:
            Diccionario con información extraída
        """
        info: dict[str, str | None] = {
            "contraparte": None,
            "identificacion": None,
            "cuenta": None,
            "referencia": None,
        }

        # Buscar transferencia entrante
        match = self.DESCRIPCION_PATTERNS["transferencia_in"].search(descripcion)
        if match:
            info["contraparte"] = match.group(1).strip()

        # Buscar transferencia saliente
        if not info["contraparte"]:
            match = self.DESCRIPCION_PATTERNS["transferencia_out"].search(descripcion)
            if match:
                info["contraparte"] = match.group(1).strip()

        # Buscar identificación (RUC/CI)
        match = self.DESCRIPCION_PATTERNS["identificacion"].search(descripcion)
        if match:
            info["identificacion"] = match.group(1)

        # Buscar número de cuenta
        match = self.DESCRIPCION_PATTERNS["cuenta"].search(descripcion)
        if match:
            info["cuenta"] = match.group(1)

        # Buscar referencia
        match = self.DESCRIPCION_PATTERNS["referencia"].search(descripcion)
        if match:
            info["referencia"] = match.group(1)

        # Buscar cheque
        if not info["referencia"]:
            match = self.DESCRIPCION_PATTERNS["cheque"].search(descripcion)
            if match:
                info["referencia"] = f"CHQ-{match.group(1)}"

        return info

    def detect_origen(self, descripcion: str) -> OrigenTransaccion:
        """
        Detecta el origen con patrones específicos de Pichincha.

        Args:
            descripcion: Descripción de la transacción

        Returns:
            Tipo de origen
        """
        desc_lower = descripcion.lower()

        # Patrones específicos de Pichincha
        if any(kw in desc_lower for kw in [
            "spi", "sipago", "transferencia spi",
            "envio externo", "recepcion externa"
        ]):
            return OrigenTransaccion.TRANSFERENCIA

        if any(kw in desc_lower for kw in [
            "dep vent", "deposito ventanilla",
            "dep efect", "deposito efectivo"
        ]):
            return OrigenTransaccion.DEPOSITO

        if any(kw in desc_lower for kw in [
            "ret vent", "retiro ventanilla", "ret atm"
        ]):
            return OrigenTransaccion.RETIRO

        if "datafast" in desc_lower or "pago pos" in desc_lower:
            return OrigenTransaccion.PAGO_TARJETA

        if any(kw in desc_lower for kw in [
            "costo mensual", "mantenimiento cta",
            "costo chequera", "costo cert"
        ]):
            return OrigenTransaccion.COMISION_BANCARIA

        if "gmt" in desc_lower or "salida divisas" in desc_lower:
            return OrigenTransaccion.IMPUESTO

        # Usar detección base
        return super().detect_origen(descripcion)
