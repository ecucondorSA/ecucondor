"""
ECUCONDOR - Parser Banco Produbanco
Parser específico para extractos del Banco Produbanco (Grupo Promerica).

Formatos soportados:
- CSV de Banca Electrónica Empresas
- Excel de Banca Electrónica
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


class ProdubancoParser(BankParser):
    """
    Parser para extractos del Banco Produbanco.

    Produbanco (parte del Grupo Promerica) tiene formatos similares
    a otros bancos centroamericanos del grupo.

    Formatos conocidos:
    1. Empresas CSV: Fecha Movimiento, Descripción, Referencia, Débito, Crédito, Saldo
    2. Empresas Excel: Similar con cabeceras adicionales de cuenta
    """

    banco = BancoEcuador.PRODUBANCO
    encoding = "utf-8"
    delimiter = ";"  # Produbanco usa punto y coma
    skip_rows = 0

    # Patrones de columnas
    COLUMN_PATTERNS = {
        "fecha": [
            "FECHA MOVIMIENTO", "FECHA", "Fecha Movimiento", "Fecha",
            "FECHA TRANSACCION", "Fecha Transaccion"
        ],
        "descripcion": [
            "DESCRIPCION", "Descripción", "DETALLE", "Detalle",
            "CONCEPTO", "Concepto"
        ],
        "referencia": [
            "REFERENCIA", "Referencia", "REF", "Ref",
            "NUMERO TRANSACCION", "No. Transaccion"
        ],
        "debito": [
            "DEBITO", "Débito", "DEBITOS", "Débitos",
            "CARGO", "Cargo", "RETIRO", "Retiro"
        ],
        "credito": [
            "CREDITO", "Crédito", "CREDITOS", "Créditos",
            "ABONO", "Abono", "DEPOSITO", "Deposito"
        ],
        "saldo": [
            "SALDO", "Saldo", "SALDO DISPONIBLE", "Saldo Disponible"
        ],
        "oficina": [
            "OFICINA", "Oficina", "SUCURSAL", "Sucursal",
            "AGENCIA", "Agencia"
        ],
    }

    # Patrones para extracción de información
    DESCRIPCION_PATTERNS = {
        # Transferencias ACH
        "ach_entrante": re.compile(
            r"(?:ACH|TRANSFER).*?(?:DE|DESDE|FROM)\s+(.+?)(?:\s+CI|\s+RUC|$)",
            re.IGNORECASE
        ),
        "ach_saliente": re.compile(
            r"(?:ACH|TRANSFER).*?(?:A|PARA|TO)\s+(.+?)(?:\s+CI|\s+RUC|$)",
            re.IGNORECASE
        ),
        # Número de cuenta beneficiario
        "cuenta_beneficiario": re.compile(
            r"(?:CTA|CUENTA)[.:\s]*(\d{8,20})",
            re.IGNORECASE
        ),
        # Identificación
        "identificacion": re.compile(
            r"(?:RUC|CI|CED)[:\s]*(\d{10,13})",
            re.IGNORECASE
        ),
        # Número de documento/voucher
        "voucher": re.compile(
            r"(?:VOUCHER|COMP|DOC)[.:\s#]*(\d+)",
            re.IGNORECASE
        ),
    }

    def detect_columns(self, df: pd.DataFrame) -> dict[str, str]:
        """
        Detecta automáticamente el mapeo de columnas para Produbanco.

        Args:
            df: DataFrame con datos

        Returns:
            Diccionario con mapeo
        """
        columns = {col.strip().upper(): col for col in df.columns}
        mapping = {}

        for field, patterns in self.COLUMN_PATTERNS.items():
            for pattern in patterns:
                pattern_upper = pattern.upper()
                for col_upper, col_orig in columns.items():
                    if pattern_upper in col_upper or col_upper in pattern_upper:
                        mapping[field] = col_orig
                        break
                if field in mapping:
                    break

        logger.debug(
            "Columnas detectadas Produbanco",
            mapping=mapping,
            columnas_archivo=list(df.columns),
        )

        return mapping

    def parse_row(self, row: pd.Series, linea: int) -> TransaccionBancaria | None:
        """
        Parsea una fila del extracto Produbanco.

        Args:
            row: Fila de pandas
            linea: Número de línea

        Returns:
            Transacción parseada o None
        """
        # Obtener mapeo si no existe
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

        # Obtener referencia
        referencia = None
        if "referencia" in col_map:
            ref = row.get(col_map["referencia"])
            if pd.notna(ref):
                referencia = str(ref).strip()

        # Extraer información de descripción
        info_extra = self._extraer_info_descripcion(descripcion)

        # Generar hash
        hash_unico = self.generate_hash(fecha, monto, descripcion, referencia)

        # Detectar origen
        origen = self.detect_origen(descripcion)

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
            referencia=referencia or info_extra.get("voucher"),
            numero_documento=referencia,
            contraparte_nombre=info_extra.get("contraparte"),
            contraparte_identificacion=info_extra.get("identificacion"),
            contraparte_cuenta=info_extra.get("cuenta"),
            datos_originales=row.to_dict(),
        )

    def _extraer_info_descripcion(self, descripcion: str) -> dict[str, str | None]:
        """
        Extrae información estructurada de descripciones de Produbanco.

        Args:
            descripcion: Texto de la descripción

        Returns:
            Diccionario con información extraída
        """
        info: dict[str, str | None] = {
            "contraparte": None,
            "identificacion": None,
            "cuenta": None,
            "voucher": None,
        }

        # Transferencias ACH entrantes
        match = self.DESCRIPCION_PATTERNS["ach_entrante"].search(descripcion)
        if match:
            info["contraparte"] = match.group(1).strip()

        # Transferencias ACH salientes
        if not info["contraparte"]:
            match = self.DESCRIPCION_PATTERNS["ach_saliente"].search(descripcion)
            if match:
                info["contraparte"] = match.group(1).strip()

        # Identificación
        match = self.DESCRIPCION_PATTERNS["identificacion"].search(descripcion)
        if match:
            info["identificacion"] = match.group(1)

        # Cuenta beneficiario
        match = self.DESCRIPCION_PATTERNS["cuenta_beneficiario"].search(descripcion)
        if match:
            info["cuenta"] = match.group(1)

        # Voucher
        match = self.DESCRIPCION_PATTERNS["voucher"].search(descripcion)
        if match:
            info["voucher"] = match.group(1)

        return info

    def detect_origen(self, descripcion: str) -> OrigenTransaccion:
        """
        Detecta origen con patrones específicos de Produbanco.

        Args:
            descripcion: Descripción

        Returns:
            Tipo de origen
        """
        desc_lower = descripcion.lower()

        # Patrones específicos de Produbanco
        if any(kw in desc_lower for kw in [
            "ach", "transferencia ach", "pago ach",
            "trx interbancaria"
        ]):
            return OrigenTransaccion.TRANSFERENCIA

        if any(kw in desc_lower for kw in [
            "dep ventanilla", "deposito efectivo",
            "dep cheque propio"
        ]):
            return OrigenTransaccion.DEPOSITO

        if any(kw in desc_lower for kw in [
            "retiro atm", "retiro ventanilla"
        ]):
            return OrigenTransaccion.RETIRO

        if any(kw in desc_lower for kw in [
            "pago establ", "consumo pos", "datafast"
        ]):
            return OrigenTransaccion.PAGO_TARJETA

        if any(kw in desc_lower for kw in [
            "costo mantenimiento", "costo emision",
            "comision", "gasto admin"
        ]):
            return OrigenTransaccion.COMISION_BANCARIA

        if "isd" in desc_lower or "gmt" in desc_lower:
            return OrigenTransaccion.IMPUESTO

        # Usar detección base
        return super().detect_origen(descripcion)
