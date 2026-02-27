"""
ECUCONDOR - Parser Base para Extractos Bancarios
Define la interfaz común para todos los parsers de bancos.
"""

import hashlib
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO, TextIO

import pandas as pd
import structlog

from src.ingestor.models import (
    BancoEcuador,
    OrigenTransaccion,
    ResultadoImportacion,
    TipoTransaccion,
    TransaccionBancaria,
)

logger = structlog.get_logger(__name__)


class BankParser(ABC):
    """
    Clase base abstracta para parsers de extractos bancarios.

    Cada banco ecuatoriano tiene su propio formato de CSV/Excel,
    por lo que cada parser implementa la lógica específica.
    """

    # Configuración del parser (a sobrescribir)
    banco: BancoEcuador
    encoding: str = "utf-8"
    delimiter: str = ","
    skip_rows: int = 0
    date_format: str = "%d/%m/%Y"

    def __init__(self, cuenta_bancaria: str):
        """
        Inicializa el parser.

        Args:
            cuenta_bancaria: Número de cuenta bancaria
        """
        self.cuenta_bancaria = cuenta_bancaria
        self._errores: list[str] = []
        self._advertencias: list[str] = []

    @abstractmethod
    def parse_row(self, row: pd.Series, linea: int) -> TransaccionBancaria | None:
        """
        Parsea una fila del extracto.

        Args:
            row: Fila de pandas
            linea: Número de línea en el archivo

        Returns:
            Transacción parseada o None si hay error
        """
        pass

    @abstractmethod
    def detect_columns(self, df: pd.DataFrame) -> dict[str, str]:
        """
        Detecta el mapeo de columnas del DataFrame.

        Args:
            df: DataFrame con los datos

        Returns:
            Diccionario con mapeo de columnas {nombre_interno: nombre_csv}
        """
        pass

    def parse_file(
        self,
        file_path: str | Path,
        *,
        encoding: str | None = None,
        delimiter: str | None = None,
    ) -> ResultadoImportacion:
        """
        Parsea un archivo de extracto bancario.

        Args:
            file_path: Ruta al archivo CSV
            encoding: Codificación (opcional, usa default del parser)
            delimiter: Delimitador (opcional, usa default del parser)

        Returns:
            Resultado de la importación
        """
        file_path = Path(file_path)
        enc = encoding or self.encoding
        delim = delimiter or self.delimiter

        self._errores = []
        self._advertencias = []

        logger.info(
            "Iniciando parseo de extracto",
            archivo=str(file_path),
            banco=self.banco.value,
            cuenta=self.cuenta_bancaria,
        )

        resultado = ResultadoImportacion(
            archivo=str(file_path),
            banco=self.banco,
            cuenta=self.cuenta_bancaria,
        )

        try:
            # Leer archivo
            df = self._read_file(file_path, enc, delim)

            if df.empty:
                resultado.errores.append("El archivo está vacío")
                return resultado

            resultado.total_lineas = len(df)

            # Detectar columnas
            column_map = self.detect_columns(df)

            # Procesar filas
            for idx, row in df.iterrows():
                linea = int(idx) + self.skip_rows + 2  # +2 por header y 0-index

                try:
                    transaccion = self.parse_row(row, linea)

                    if transaccion is None:
                        resultado.transacciones_error += 1
                        continue

                    # Agregar metadatos
                    transaccion.archivo_origen = str(file_path.name)
                    transaccion.linea_origen = linea

                    resultado.transacciones.append(transaccion)
                    resultado.transacciones_nuevas += 1

                    # Acumular montos
                    if transaccion.tipo == TipoTransaccion.CREDITO:
                        resultado.monto_total_creditos += transaccion.monto
                    else:
                        resultado.monto_total_debitos += transaccion.monto

                except Exception as e:
                    self._errores.append(f"Línea {linea}: {str(e)}")
                    resultado.transacciones_error += 1

        except Exception as e:
            logger.error("Error parseando archivo", error=str(e), exc_info=True)
            resultado.errores.append(f"Error general: {str(e)}")

        resultado.errores.extend(self._errores)
        resultado.advertencias.extend(self._advertencias)

        logger.info(
            "Parseo completado",
            total=resultado.total_lineas,
            nuevas=resultado.transacciones_nuevas,
            errores=resultado.transacciones_error,
            creditos=float(resultado.monto_total_creditos),
            debitos=float(resultado.monto_total_debitos),
        )

        return resultado

    def parse_bytes(
        self,
        content: bytes,
        filename: str,
        *,
        encoding: str | None = None,
        delimiter: str | None = None,
    ) -> ResultadoImportacion:
        """
        Parsea contenido de bytes (para uploads HTTP).

        Args:
            content: Contenido del archivo en bytes
            filename: Nombre del archivo
            encoding: Codificación
            delimiter: Delimitador

        Returns:
            Resultado de la importación
        """
        import io
        import tempfile

        # Escribir a archivo temporal
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=Path(filename).suffix,
            delete=False
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            resultado = self.parse_file(
                tmp_path,
                encoding=encoding,
                delimiter=delimiter,
            )
            # Corregir nombre de archivo
            resultado.archivo = filename
            for tx in resultado.transacciones:
                tx.archivo_origen = filename
            return resultado
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _read_file(
        self,
        file_path: Path,
        encoding: str,
        delimiter: str,
    ) -> pd.DataFrame:
        """
        Lee el archivo CSV/Excel.

        Args:
            file_path: Ruta al archivo
            encoding: Codificación
            delimiter: Delimitador

        Returns:
            DataFrame con los datos
        """
        suffix = file_path.suffix.lower()

        if suffix in [".xlsx", ".xls"]:
            df = pd.read_excel(
                file_path,
                skiprows=self.skip_rows,
                engine="openpyxl" if suffix == ".xlsx" else "xlrd",
            )
        else:
            # Intentar detectar encoding si falla
            try:
                df = pd.read_csv(
                    file_path,
                    encoding=encoding,
                    delimiter=delimiter,
                    skiprows=self.skip_rows,
                    on_bad_lines="warn",
                )
            except UnicodeDecodeError:
                # Intentar con latin-1 (común en Ecuador)
                df = pd.read_csv(
                    file_path,
                    encoding="latin-1",
                    delimiter=delimiter,
                    skiprows=self.skip_rows,
                    on_bad_lines="warn",
                )
                self._advertencias.append(
                    f"Archivo leído con encoding latin-1 (encoding original falló)"
                )

        # Limpiar nombres de columnas
        df.columns = df.columns.str.strip()

        return df

    def generate_hash(
        self,
        fecha: date,
        monto: Decimal,
        descripcion: str,
        referencia: str | None = None,
    ) -> str:
        """
        Genera hash único para deduplicación.

        El hash se basa en:
        - Banco
        - Cuenta
        - Fecha
        - Monto
        - Descripción
        - Referencia (si existe)

        Args:
            fecha: Fecha de la transacción
            monto: Monto
            descripcion: Descripción
            referencia: Referencia opcional

        Returns:
            Hash SHA-256 de 16 caracteres
        """
        componentes = [
            self.banco.value,
            self.cuenta_bancaria,
            fecha.isoformat(),
            str(monto),
            descripcion.strip().lower(),
        ]

        if referencia:
            componentes.append(referencia.strip())

        cadena = "|".join(componentes)
        return hashlib.sha256(cadena.encode()).hexdigest()[:16]

    def parse_date(self, value: Any) -> date | None:
        """
        Parsea una fecha en varios formatos comunes.

        Args:
            value: Valor a parsear

        Returns:
            Fecha o None si no se puede parsear
        """
        if pd.isna(value):
            return None

        if isinstance(value, date):
            return value

        if isinstance(value, pd.Timestamp):
            return value.date()

        str_value = str(value).strip()

        # Formatos comunes en Ecuador
        formatos = [
            "%d/%m/%Y",      # 25/11/2025
            "%d-%m-%Y",      # 25-11-2025
            "%Y-%m-%d",      # 2025-11-25
            "%d/%m/%y",      # 25/11/25
            "%d-%m-%y",      # 25-11-25
            "%d %b %Y",      # 25 Nov 2025
            "%d %B %Y",      # 25 Noviembre 2025
        ]

        from datetime import datetime

        for fmt in formatos:
            try:
                return datetime.strptime(str_value, fmt).date()
            except ValueError:
                continue

        self._errores.append(f"No se pudo parsear fecha: {value}")
        return None

    def parse_amount(self, value: Any) -> Decimal | None:
        """
        Parsea un monto monetario.

        Maneja formatos:
        - 1234.56 (punto decimal)
        - 1.234,56 (formato europeo/Ecuador)
        - -1234.56 (negativos)
        - (1234.56) (negativos entre paréntesis)

        Args:
            value: Valor a parsear

        Returns:
            Decimal o None
        """
        if pd.isna(value):
            return None

        str_value = str(value).strip()

        if not str_value or str_value == "-":
            return None

        # Detectar negativos entre paréntesis
        negativo = False
        if str_value.startswith("(") and str_value.endswith(")"):
            str_value = str_value[1:-1]
            negativo = True
        elif str_value.startswith("-"):
            str_value = str_value[1:]
            negativo = True

        # Remover símbolos de moneda
        str_value = str_value.replace("$", "").replace("USD", "").strip()

        # Detectar formato (europeo vs americano)
        if "," in str_value and "." in str_value:
            # Determinar cuál es el separador decimal
            last_comma = str_value.rfind(",")
            last_dot = str_value.rfind(".")

            if last_comma > last_dot:
                # Formato europeo: 1.234,56
                str_value = str_value.replace(".", "").replace(",", ".")
            else:
                # Formato americano: 1,234.56
                str_value = str_value.replace(",", "")
        elif "," in str_value:
            # Solo coma - asumir separador decimal si hay 2 decimales
            parts = str_value.split(",")
            if len(parts) == 2 and len(parts[1]) <= 2:
                str_value = str_value.replace(",", ".")
            else:
                str_value = str_value.replace(",", "")

        try:
            amount = Decimal(str_value)
            if negativo:
                amount = -amount
            return amount
        except Exception:
            self._errores.append(f"No se pudo parsear monto: {value}")
            return None

    def detect_transaction_type(
        self,
        credito: Decimal | None,
        debito: Decimal | None,
    ) -> tuple[TipoTransaccion, Decimal]:
        """
        Detecta tipo de transacción basado en columnas crédito/débito.

        Args:
            credito: Valor de columna crédito
            debito: Valor de columna débito

        Returns:
            Tupla (tipo, monto_absoluto)
        """
        if credito and credito > 0:
            return TipoTransaccion.CREDITO, abs(credito)
        elif debito and debito > 0:
            return TipoTransaccion.DEBITO, abs(debito)
        elif credito and credito < 0:
            return TipoTransaccion.DEBITO, abs(credito)
        elif debito and debito < 0:
            return TipoTransaccion.CREDITO, abs(debito)
        else:
            # Default
            return TipoTransaccion.DEBITO, Decimal("0")

    def detect_origen(self, descripcion: str) -> OrigenTransaccion:
        """
        Detecta el origen de la transacción por la descripción.

        Args:
            descripcion: Descripción de la transacción

        Returns:
            Tipo de origen detectado
        """
        desc_lower = descripcion.lower()

        # Transferencias
        if any(kw in desc_lower for kw in [
            "transfer", "traspaso", "envio", "recibido de",
            "spei", "ach", "swift", "interbancaria"
        ]):
            return OrigenTransaccion.TRANSFERENCIA

        # Depósitos
        if any(kw in desc_lower for kw in [
            "deposito", "depósito", "consignacion", "consignación"
        ]):
            return OrigenTransaccion.DEPOSITO

        # Retiros
        if any(kw in desc_lower for kw in [
            "retiro", "cajero", "atm", "efectivo"
        ]):
            return OrigenTransaccion.RETIRO

        # Cheques
        if any(kw in desc_lower for kw in [
            "cheque", "ch/", "chq"
        ]):
            return OrigenTransaccion.CHEQUE

        # Tarjeta
        if any(kw in desc_lower for kw in [
            "tarjeta", "card", "pos", "datafast", "medianet"
        ]):
            return OrigenTransaccion.PAGO_TARJETA

        # Comisiones bancarias
        if any(kw in desc_lower for kw in [
            "comision", "comisión", "cargo", "mantenimiento",
            "costo", "fee", "penalidad"
        ]):
            return OrigenTransaccion.COMISION_BANCARIA

        # Intereses
        if any(kw in desc_lower for kw in [
            "interes", "interés", "interest"
        ]):
            return OrigenTransaccion.INTERES

        # Impuestos
        if any(kw in desc_lower for kw in [
            "impuesto", "iva", "isd", "ice", "sri", "gmt"
        ]):
            return OrigenTransaccion.IMPUESTO

        return OrigenTransaccion.OTRO


def get_parser(banco: BancoEcuador, cuenta: str) -> BankParser:
    """
    Factory para obtener el parser apropiado.

    Args:
        banco: Banco a parsear
        cuenta: Número de cuenta

    Returns:
        Parser específico para el banco

    Raises:
        ValueError: Si el banco no está soportado
    """
    from src.ingestor.parsers.pichincha import PichinchaParser
    from src.ingestor.parsers.produbanco import ProdubancoParser

    parsers = {
        BancoEcuador.PICHINCHA: PichinchaParser,
        BancoEcuador.PRODUBANCO: ProdubancoParser,
    }

    parser_class = parsers.get(banco)

    if parser_class is None:
        raise ValueError(f"Banco no soportado: {banco.value}")

    return parser_class(cuenta)
