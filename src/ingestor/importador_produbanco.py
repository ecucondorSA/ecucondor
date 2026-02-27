"""
ECUCONDOR - Importador de Extracto Bancario Produbanco
Procesa archivos Excel de Produbanco y genera liquidaciones de compra automaticamente.

Modelo de Negocio:
- Creditos (+) = Luis (comprador) paga a ECUCONDOR = VENTA de cripto
- Debitos (-) = ECUCONDOR paga a Paula (vendedor) = COMPRA de cripto

Documentos generados:
- Por cada DEBITO: Liquidacion de Compra (tipo 03) al vendedor
- Comision 1.5% se calcula sobre el monto total
"""

from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal
from typing import Optional
import re

import pandas as pd
import structlog

from src.db.supabase import get_supabase_client

logger = structlog.get_logger(__name__)


@dataclass
class MovimientoBancario:
    """Representa un movimiento del extracto bancario."""
    fecha: datetime
    referencia: str
    descripcion: str
    tipo: str  # '+' o '-'
    valor: Decimal
    saldo_contable: Optional[Decimal] = None
    saldo_disponible: Optional[Decimal] = None
    oficina: Optional[str] = None


class ImportadorProdubanco:
    """
    Importador de extractos bancarios de Produbanco.

    Formato esperado del Excel:
    - Filas 0-7: Encabezado con info de cuenta
    - Fila 8: Nombres de columnas (FECHA, REFERENCIA, DESCRIPCION, +/-, VALOR, etc.)
    - Filas 9+: Datos de movimientos
    """

    def __init__(self, supabase=None):
        self.supabase = supabase or get_supabase_client()
        self.movimientos: list[MovimientoBancario] = []

    def leer_excel(self, file_path: str) -> list[MovimientoBancario]:
        """
        Lee el archivo Excel de Produbanco.

        Args:
            file_path: Ruta al archivo Excel

        Returns:
            Lista de movimientos bancarios
        """
        try:
            # Leer saltando el encabezado (8 filas)
            df = pd.read_excel(file_path, engine='openpyxl', skiprows=8)

            # Renombrar columnas
            df.columns = ['Fecha', 'Referencia', 'Descripcion', 'Tipo', 'Valor',
                         'SaldoContable', 'SaldoDisponible', 'Oficina']

            # Filtrar filas con datos validos
            df = df[df['Fecha'].notna() & df['Valor'].notna()]

            movimientos = []
            for _, row in df.iterrows():
                try:
                    # Parsear fecha
                    fecha = self._parsear_fecha(row['Fecha'])
                    if not fecha:
                        continue

                    mov = MovimientoBancario(
                        fecha=fecha,
                        referencia=str(row['Referencia']) if pd.notna(row['Referencia']) else '',
                        descripcion=str(row['Descripcion']) if pd.notna(row['Descripcion']) else '',
                        tipo=str(row['Tipo']).strip() if pd.notna(row['Tipo']) else '',
                        valor=Decimal(str(row['Valor'])) if pd.notna(row['Valor']) else Decimal("0"),
                        saldo_contable=Decimal(str(row['SaldoContable'])) if pd.notna(row['SaldoContable']) else None,
                        saldo_disponible=Decimal(str(row['SaldoDisponible'])) if pd.notna(row['SaldoDisponible']) else None,
                        oficina=str(row['Oficina']) if pd.notna(row['Oficina']) else None
                    )
                    movimientos.append(mov)
                except Exception as e:
                    logger.warning(f"Error procesando fila: {e}")
                    continue

            self.movimientos = movimientos
            logger.info(f"Leidos {len(movimientos)} movimientos de {file_path}")
            return movimientos

        except Exception as e:
            logger.error(f"Error leyendo Excel: {e}")
            raise

    def _parsear_fecha(self, fecha_str) -> Optional[datetime]:
        """Parsea fecha del formato de Produbanco."""
        if pd.isna(fecha_str):
            return None

        fecha_str = str(fecha_str)

        # Formatos comunes de Produbanco
        formatos = [
            "%m/%d/%Y %I:%M:%S %p",  # 01/02/2025 02:14:00 PM
            "%m/%d/%Y %H:%M:%S",     # 01/02/2025 14:14:00
            "%d/%m/%Y %H:%M:%S",     # 02/01/2025 14:14:00
            "%Y-%m-%d %H:%M:%S",     # 2025-01-02 14:14:00
            "%m/%d/%Y",              # 01/02/2025
            "%d/%m/%Y",              # 02/01/2025
        ]

        for fmt in formatos:
            try:
                return datetime.strptime(fecha_str, fmt)
            except ValueError:
                continue

        # Si es datetime de pandas
        if isinstance(fecha_str, (datetime, pd.Timestamp)):
            return fecha_str

        return None

    async def importar_transacciones_bancarias(self) -> dict:
        """
        Importa los movimientos a la tabla transacciones_bancarias.

        Returns:
            dict con estadisticas de importacion
        """
        if not self.movimientos:
            return {"error": "No hay movimientos para importar"}

        importados = 0
        duplicados = 0
        errores = 0

        for mov in self.movimientos:
            try:
                # Verificar si ya existe por referencia
                existing = self.supabase.table('transacciones_bancarias').select('id').eq(
                    'referencia', mov.referencia
                ).execute()

                if existing.data:
                    duplicados += 1
                    continue

                # Determinar tipo
                tipo = 'credito' if mov.tipo == '+' else 'debito'

                # Insertar (sin categoria - el campo no existe en la tabla)
                data = {
                    'fecha': mov.fecha.date().isoformat(),
                    'referencia': mov.referencia,
                    'descripcion': mov.descripcion,
                    'tipo': tipo,
                    'monto': float(mov.valor),
                    'banco': 'PRODUBANCO',
                    'estado': 'pendiente'
                }

                self.supabase.table('transacciones_bancarias').insert(data).execute()
                importados += 1

            except Exception as e:
                logger.error(f"Error importando movimiento {mov.referencia}: {e}")
                errores += 1

        return {
            "total": len(self.movimientos),
            "importados": importados,
            "duplicados": duplicados,
            "errores": errores
        }

    async def generar_liquidaciones_compra(
        self,
        solo_debitos: bool = True,
        cliente_default: str = "9999999999999",
        nombre_default: str = "CONSUMIDOR FINAL",
        monto_minimo: Decimal = Decimal("1.00")  # Excluir comisiones bancarias (<$1)
    ) -> dict:
        """
        Genera liquidaciones de compra desde los movimientos.

        Para cripto:
        - Debitos (-) = Pagos a vendedores = Liquidacion de Compra
        - Se excluyen montos pequeños ($0.41) que son comisiones bancarias interbancarias

        Args:
            solo_debitos: Si True, solo procesa debitos (compras)
            cliente_default: Cedula por defecto
            nombre_default: Nombre por defecto
            monto_minimo: Monto minimo para considerar como cripto (excluye comisiones bancarias)

        Returns:
            dict con estadisticas
        """
        from src.compras.liquidaciones import LiquidacionService, LiquidacionCripto

        if not self.movimientos:
            return {"error": "No hay movimientos para procesar"}

        # Filtrar movimientos: solo debitos Y excluyendo comisiones bancarias pequeñas
        if solo_debitos:
            movimientos = [m for m in self.movimientos if m.tipo == '-' and m.valor >= monto_minimo]
            comisiones_excluidas = len([m for m in self.movimientos if m.tipo == '-' and m.valor < monto_minimo])
            logger.info(f"Excluidas {comisiones_excluidas} comisiones bancarias (montos < ${monto_minimo})")
        else:
            movimientos = [m for m in self.movimientos if m.valor >= monto_minimo]

        service = LiquidacionService(self.supabase)
        creadas = 0
        errores = 0
        total_monto = Decimal("0")

        for mov in movimientos:
            try:
                # Crear liquidacion (sin contabilizar - tabla no tiene esquema correcto)
                liquidacion_data = LiquidacionCripto(
                    vendedor_tipo_id="07",  # Consumidor final
                    vendedor_identificacion=cliente_default,
                    vendedor_nombre=nombre_default,
                    fecha_emision=mov.fecha.date(),
                    concepto=f"Compra cripto - Ref: {mov.referencia}",
                    monto_cripto=mov.valor,
                    tipo_cripto="USDT",
                    aplica_retencion_ir=False,
                    auto_contabilizar=False  # Desactivado - esquema contable incompleto
                )

                result = await service.crear_liquidacion_cripto(liquidacion_data)

                if result.get('success'):
                    creadas += 1
                    total_monto += mov.valor
                else:
                    errores += 1
                    logger.error(f"Error en liquidacion {mov.referencia}: {result.get('error')}")

            except Exception as e:
                errores += 1
                logger.error(f"Error procesando {mov.referencia}: {e}")

        # Calcular comision total (1.5%)
        comision_total = total_monto * Decimal("0.015")
        iva_comision = comision_total * Decimal("0.15")

        return {
            "movimientos_procesados": len(movimientos),
            "liquidaciones_creadas": creadas,
            "errores": errores,
            "total_compras_cripto": float(total_monto),
            "comision_generada": float(comision_total),
            "iva_comision": float(iva_comision)
        }

    def resumen(self) -> dict:
        """Genera resumen de los movimientos leidos."""
        if not self.movimientos:
            return {"error": "No hay movimientos"}

        creditos = [m for m in self.movimientos if m.tipo == '+']
        debitos = [m for m in self.movimientos if m.tipo == '-']

        total_creditos = sum(m.valor for m in creditos)
        total_debitos = sum(m.valor for m in debitos)

        return {
            "total_movimientos": len(self.movimientos),
            "creditos": {
                "cantidad": len(creditos),
                "total": float(total_creditos)
            },
            "debitos": {
                "cantidad": len(debitos),
                "total": float(total_debitos)
            },
            "neto": float(total_creditos - total_debitos),
            "fecha_inicio": min(m.fecha for m in self.movimientos).isoformat() if self.movimientos else None,
            "fecha_fin": max(m.fecha for m in self.movimientos).isoformat() if self.movimientos else None
        }


async def procesar_extracto_produbanco(
    file_path: str,
    generar_liquidaciones: bool = True,
    solo_debitos: bool = True,
    importar_a_tabla: bool = False  # Por defecto NO importa a tabla bancaria
) -> dict:
    """
    Funcion de alto nivel para procesar un extracto de Produbanco.

    Args:
        file_path: Ruta al archivo Excel
        generar_liquidaciones: Si True, genera las liquidaciones de compra
        solo_debitos: Si True, solo procesa debitos para liquidaciones
        importar_a_tabla: Si True, tambien importa a transacciones_bancarias

    Returns:
        dict con resultados del procesamiento
    """
    importador = ImportadorProdubanco()

    # 1. Leer Excel
    movimientos = importador.leer_excel(file_path)
    resumen = importador.resumen()

    result = {
        "archivo": file_path,
        "resumen": resumen
    }

    # 2. Importar a transacciones bancarias (opcional)
    if importar_a_tabla:
        import_result = await importador.importar_transacciones_bancarias()
        result["importacion_bancaria"] = import_result

    # 3. Generar liquidaciones si se solicita
    if generar_liquidaciones:
        liq_result = await importador.generar_liquidaciones_compra(
            solo_debitos=solo_debitos
        )
        result["liquidaciones"] = liq_result

    return result
