"""
ECUCONDOR - Módulo de Reportes Contables
Genera Balance General, Estado de Resultados y Libro Mayor.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from dataclasses import dataclass, field
from enum import Enum


class TipoCuenta(str, Enum):
    """Tipos de cuenta contable."""
    ACTIVO = "activo"
    PASIVO = "pasivo"
    PATRIMONIO = "patrimonio"
    INGRESO = "ingreso"
    GASTO = "gasto"


@dataclass
class LineaReporte:
    """Línea de un reporte contable."""
    codigo: str
    nombre: str
    nivel: int
    saldo: Decimal = Decimal("0")
    es_titulo: bool = False

    @property
    def indentacion(self) -> str:
        """Retorna espacios de indentación según nivel."""
        return "  " * (self.nivel - 1)

    def formato_saldo(self) -> str:
        """Formatea el saldo con signo."""
        if self.saldo >= 0:
            return f"${self.saldo:,.2f}"
        return f"-${abs(self.saldo):,.2f}"


@dataclass
class SeccionBalance:
    """Sección del balance (Activos, Pasivos, etc.)."""
    nombre: str
    lineas: list[LineaReporte] = field(default_factory=list)
    total: Decimal = Decimal("0")

    def agregar_linea(self, linea: LineaReporte):
        self.lineas.append(linea)
        if not linea.es_titulo:
            self.total += linea.saldo


@dataclass
class BalanceGeneral:
    """Balance General (Estado de Situación Financiera)."""
    fecha_corte: date
    empresa: str

    activos: SeccionBalance = field(default_factory=lambda: SeccionBalance("ACTIVOS"))
    pasivos: SeccionBalance = field(default_factory=lambda: SeccionBalance("PASIVOS"))
    patrimonio: SeccionBalance = field(default_factory=lambda: SeccionBalance("PATRIMONIO"))

    @property
    def total_activos(self) -> Decimal:
        return self.activos.total

    @property
    def total_pasivos(self) -> Decimal:
        return self.pasivos.total

    @property
    def total_patrimonio(self) -> Decimal:
        return self.patrimonio.total

    @property
    def pasivo_mas_patrimonio(self) -> Decimal:
        return self.total_pasivos + self.total_patrimonio

    @property
    def esta_cuadrado(self) -> bool:
        """Verifica ecuación contable: Activo = Pasivo + Patrimonio."""
        diff = abs(self.total_activos - self.pasivo_mas_patrimonio)
        return diff < Decimal("0.01")

    def to_text(self) -> str:
        """Genera reporte en texto."""
        lineas = [
            "=" * 70,
            f"BALANCE GENERAL - {self.empresa}",
            f"Al {self.fecha_corte.strftime('%d de %B de %Y')}",
            "=" * 70,
            "",
            "ACTIVOS",
            "-" * 70,
        ]

        for l in self.activos.lineas:
            if l.es_titulo:
                lineas.append(f"{l.indentacion}{l.nombre}")
            else:
                lineas.append(f"{l.indentacion}{l.codigo} {l.nombre:<40} {l.formato_saldo():>15}")

        lineas.extend([
            "-" * 70,
            f"{'TOTAL ACTIVOS':<55} ${self.total_activos:>12,.2f}",
            "",
            "PASIVOS",
            "-" * 70,
        ])

        for l in self.pasivos.lineas:
            if l.es_titulo:
                lineas.append(f"{l.indentacion}{l.nombre}")
            else:
                lineas.append(f"{l.indentacion}{l.codigo} {l.nombre:<40} {l.formato_saldo():>15}")

        lineas.extend([
            "-" * 70,
            f"{'TOTAL PASIVOS':<55} ${self.total_pasivos:>12,.2f}",
            "",
            "PATRIMONIO",
            "-" * 70,
        ])

        for l in self.patrimonio.lineas:
            if l.es_titulo:
                lineas.append(f"{l.indentacion}{l.nombre}")
            else:
                lineas.append(f"{l.indentacion}{l.codigo} {l.nombre:<40} {l.formato_saldo():>15}")

        lineas.extend([
            "-" * 70,
            f"{'TOTAL PATRIMONIO':<55} ${self.total_patrimonio:>12,.2f}",
            "",
            "=" * 70,
            f"{'PASIVO + PATRIMONIO':<55} ${self.pasivo_mas_patrimonio:>12,.2f}",
            "=" * 70,
        ])

        if self.esta_cuadrado:
            lineas.append("Estado: CUADRADO")
        else:
            diff = self.total_activos - self.pasivo_mas_patrimonio
            lineas.append(f"Estado: DESCUADRADO (Diferencia: ${diff:,.2f})")

        return "\n".join(lineas)


@dataclass
class EstadoResultados:
    """Estado de Resultados (Pérdidas y Ganancias)."""
    fecha_inicio: date
    fecha_fin: date
    empresa: str

    ingresos: list[LineaReporte] = field(default_factory=list)
    gastos: list[LineaReporte] = field(default_factory=list)

    total_ingresos: Decimal = Decimal("0")
    total_gastos: Decimal = Decimal("0")

    @property
    def utilidad_bruta(self) -> Decimal:
        """Utilidad/Pérdida del período."""
        return self.total_ingresos - self.total_gastos

    @property
    def es_utilidad(self) -> bool:
        return self.utilidad_bruta >= 0

    def to_text(self) -> str:
        """Genera reporte en texto."""
        lineas = [
            "=" * 70,
            f"ESTADO DE RESULTADOS - {self.empresa}",
            f"Del {self.fecha_inicio.strftime('%d/%m/%Y')} al {self.fecha_fin.strftime('%d/%m/%Y')}",
            "=" * 70,
            "",
            "INGRESOS",
            "-" * 70,
        ]

        for l in self.ingresos:
            if l.es_titulo:
                lineas.append(f"{l.indentacion}{l.nombre}")
            else:
                lineas.append(f"{l.indentacion}{l.codigo} {l.nombre:<40} {l.formato_saldo():>15}")

        lineas.extend([
            "-" * 70,
            f"{'TOTAL INGRESOS':<55} ${self.total_ingresos:>12,.2f}",
            "",
            "GASTOS",
            "-" * 70,
        ])

        for l in self.gastos:
            if l.es_titulo:
                lineas.append(f"{l.indentacion}{l.nombre}")
            else:
                lineas.append(f"{l.indentacion}{l.codigo} {l.nombre:<40} {l.formato_saldo():>15}")

        lineas.extend([
            "-" * 70,
            f"{'TOTAL GASTOS':<55} ${self.total_gastos:>12,.2f}",
            "",
            "=" * 70,
        ])

        if self.es_utilidad:
            lineas.append(f"{'UTILIDAD DEL EJERCICIO':<55} ${self.utilidad_bruta:>12,.2f}")
        else:
            lineas.append(f"{'PÉRDIDA DEL EJERCICIO':<55} -${abs(self.utilidad_bruta):>12,.2f}")

        lineas.append("=" * 70)

        return "\n".join(lineas)


@dataclass
class MovimientoMayor:
    """Movimiento individual en el libro mayor."""
    fecha: date
    numero_asiento: int
    concepto: str
    debe: Decimal = Decimal("0")
    haber: Decimal = Decimal("0")
    saldo: Decimal = Decimal("0")


@dataclass
class LibroMayor:
    """Libro Mayor de una cuenta."""
    cuenta_codigo: str
    cuenta_nombre: str
    fecha_inicio: date
    fecha_fin: date
    empresa: str

    saldo_inicial: Decimal = Decimal("0")
    movimientos: list[MovimientoMayor] = field(default_factory=list)

    total_debe: Decimal = Decimal("0")
    total_haber: Decimal = Decimal("0")
    saldo_final: Decimal = Decimal("0")

    def to_text(self) -> str:
        """Genera reporte en texto."""
        lineas = [
            "=" * 100,
            f"LIBRO MAYOR - {self.empresa}",
            f"Cuenta: {self.cuenta_codigo} - {self.cuenta_nombre}",
            f"Período: {self.fecha_inicio.strftime('%d/%m/%Y')} al {self.fecha_fin.strftime('%d/%m/%Y')}",
            "=" * 100,
            "",
            f"{'FECHA':<12} {'#':<8} {'CONCEPTO':<40} {'DEBE':>12} {'HABER':>12} {'SALDO':>12}",
            "-" * 100,
            f"{'SALDO INICIAL':<62} {'':<12} {'':<12} ${self.saldo_inicial:>10,.2f}",
        ]

        for m in self.movimientos:
            debe_str = f"${m.debe:,.2f}" if m.debe > 0 else ""
            haber_str = f"${m.haber:,.2f}" if m.haber > 0 else ""
            saldo_str = f"${m.saldo:,.2f}" if m.saldo >= 0 else f"-${abs(m.saldo):,.2f}"

            lineas.append(
                f"{m.fecha.strftime('%d/%m/%Y'):<12} "
                f"{m.numero_asiento:<8} "
                f"{m.concepto[:40]:<40} "
                f"{debe_str:>12} "
                f"{haber_str:>12} "
                f"{saldo_str:>12}"
            )

        lineas.extend([
            "-" * 100,
            f"{'TOTALES':<62} ${self.total_debe:>10,.2f} ${self.total_haber:>10,.2f} ${self.saldo_final:>10,.2f}",
            "=" * 100,
        ])

        return "\n".join(lineas)


class GeneradorReportes:
    """
    Generador de reportes contables.

    Consulta la base de datos y genera los reportes financieros.
    """

    def __init__(self, supabase_client):
        self.supabase = supabase_client

    def obtener_saldos_cuentas(
        self,
        fecha_inicio: date,
        fecha_fin: date,
        tipo_cuenta: str | None = None
    ) -> dict[str, dict[str, Any]]:
        """
        Obtiene saldos de cuentas sumando movimientos.

        Returns:
            Dict con codigo_cuenta -> {nombre, tipo, debe, haber, saldo}
        """
        # Query para obtener saldos agrupados por cuenta
        query = """
        SELECT
            c.codigo,
            c.nombre,
            c.tipo,
            c.nivel,
            c.naturaleza,
            COALESCE(SUM(m.debe), 0) as total_debe,
            COALESCE(SUM(m.haber), 0) as total_haber
        FROM cuentas_contables c
        LEFT JOIN movimientos_contables m ON c.codigo = m.cuenta_codigo
        LEFT JOIN asientos_contables a ON m.asiento_id = a.id
        WHERE c.es_movimiento = true
        AND (a.fecha IS NULL OR (a.fecha >= '{0}' AND a.fecha <= '{1}'))
        AND (a.estado IS NULL OR a.estado != 'anulado')
        {2}
        GROUP BY c.codigo, c.nombre, c.tipo, c.nivel, c.naturaleza
        ORDER BY c.codigo
        """.format(
            fecha_inicio.isoformat(),
            fecha_fin.isoformat(),
            f"AND c.tipo = '{tipo_cuenta}'" if tipo_cuenta else ""
        )

        result = self.supabase.rpc('sql_query', {'query': query}).execute()

        # Fallback: usar consultas directas si RPC no está disponible
        if not result.data:
            return self._obtener_saldos_directo(fecha_inicio, fecha_fin, tipo_cuenta)

        saldos = {}
        for row in result.data:
            codigo = row['codigo']
            debe = Decimal(str(row['total_debe']))
            haber = Decimal(str(row['total_haber']))
            naturaleza = row['naturaleza']

            # Calcular saldo según naturaleza
            if naturaleza == 'deudora':
                saldo = debe - haber
            else:
                saldo = haber - debe

            saldos[codigo] = {
                'nombre': row['nombre'],
                'tipo': row['tipo'],
                'nivel': row['nivel'],
                'naturaleza': naturaleza,
                'debe': debe,
                'haber': haber,
                'saldo': saldo,
            }

        return saldos

    def _obtener_saldos_directo(
        self,
        fecha_inicio: date,
        fecha_fin: date,
        tipo_cuenta: str | None = None
    ) -> dict[str, dict[str, Any]]:
        """Obtiene saldos usando consultas directas (fallback)."""
        # Obtener cuentas
        query = self.supabase.table('cuentas_contables').select('*').eq('es_movimiento', True)
        if tipo_cuenta:
            query = query.eq('tipo', tipo_cuenta)
        cuentas = query.execute().data

        # Obtener movimientos del período
        movimientos = self.supabase.table('movimientos_contables').select(
            'cuenta_codigo, debe, haber, asientos_contables!inner(fecha, estado)'
        ).gte(
            'asientos_contables.fecha', fecha_inicio.isoformat()
        ).lte(
            'asientos_contables.fecha', fecha_fin.isoformat()
        ).neq(
            'asientos_contables.estado', 'anulado'
        ).execute().data

        # Agrupar movimientos por cuenta
        mov_por_cuenta: dict[str, dict] = {}
        for m in movimientos:
            codigo = m['cuenta_codigo']
            if codigo not in mov_por_cuenta:
                mov_por_cuenta[codigo] = {'debe': Decimal("0"), 'haber': Decimal("0")}
            mov_por_cuenta[codigo]['debe'] += Decimal(str(m['debe']))
            mov_por_cuenta[codigo]['haber'] += Decimal(str(m['haber']))

        saldos = {}
        for cuenta in cuentas:
            codigo = cuenta['codigo']
            mov = mov_por_cuenta.get(codigo, {'debe': Decimal("0"), 'haber': Decimal("0")})
            naturaleza = cuenta.get('naturaleza', 'deudora')

            if naturaleza == 'deudora':
                saldo = mov['debe'] - mov['haber']
            else:
                saldo = mov['haber'] - mov['debe']

            saldos[codigo] = {
                'nombre': cuenta['nombre'],
                'tipo': cuenta['tipo'],
                'nivel': cuenta.get('nivel', 1),
                'naturaleza': naturaleza,
                'debe': mov['debe'],
                'haber': mov['haber'],
                'saldo': saldo,
            }

        return saldos

    def generar_balance_general(
        self,
        fecha_corte: date,
        empresa: str,
        incluir_cuentas_cero: bool = False
    ) -> BalanceGeneral:
        """
        Genera el Balance General a una fecha de corte.

        Incluye el Resultado del Ejercicio (Ingresos - Gastos) como parte
        del Patrimonio para cumplir con la ecuación contable:
        Activos = Pasivos + Patrimonio + Resultado del Ejercicio
        """
        # Obtener saldos desde inicio de operaciones hasta fecha de corte
        fecha_inicio = date(2020, 1, 1)  # Fecha arbitraria de inicio
        saldos = self._obtener_saldos_directo(fecha_inicio, fecha_corte)

        balance = BalanceGeneral(
            fecha_corte=fecha_corte,
            empresa=empresa
        )

        # Acumuladores para calcular Resultado del Ejercicio
        total_ingresos = Decimal("0")
        total_gastos = Decimal("0")

        # Clasificar cuentas por tipo
        # IMPORTANTE: Usamos el saldo CON SIGNO para mantener la ecuación contable
        # Un activo con saldo negativo indica saldo acreedor (anormal)
        # Un pasivo con saldo negativo indica saldo deudor (anormal)
        for codigo, datos in sorted(saldos.items()):
            tipo = datos['tipo']
            saldo_real = datos['saldo']  # Saldo con signo correcto

            # Acumular ingresos y gastos para el resultado del ejercicio
            if tipo == 'ingreso':
                total_ingresos += saldo_real  # Usar saldo real, no absoluto
                continue  # No mostrar en balance, solo en estado de resultados
            elif tipo == 'gasto':
                total_gastos += saldo_real  # Usar saldo real, no absoluto
                continue  # No mostrar en balance, solo en estado de resultados

            if not incluir_cuentas_cero and saldo_real == 0:
                continue

            # Para presentación: activos positivos se muestran como activos
            # Pasivos positivos se muestran como pasivos
            # Los signos negativos se mantienen para cuadrar la ecuación
            linea = LineaReporte(
                codigo=codigo,
                nombre=datos['nombre'],
                nivel=datos['nivel'],
                saldo=saldo_real,  # Mantener el signo para ecuación contable
            )

            if tipo == 'activo':
                balance.activos.agregar_linea(linea)
            elif tipo == 'pasivo':
                balance.pasivos.agregar_linea(linea)
            elif tipo == 'patrimonio':
                balance.patrimonio.agregar_linea(linea)

        # Agregar Resultado del Ejercicio al Patrimonio
        # Utilidad = Ingresos - Gastos (positivo = utilidad, negativo = pérdida)
        resultado_ejercicio = total_ingresos - total_gastos

        if resultado_ejercicio != Decimal("0") or incluir_cuentas_cero:
            # Determinar si es utilidad o pérdida
            if resultado_ejercicio >= 0:
                nombre_resultado = "Utilidad del Ejercicio"
            else:
                nombre_resultado = "Pérdida del Ejercicio"

            linea_resultado = LineaReporte(
                codigo="3.9.9.01",  # Código especial para resultado del ejercicio
                nombre=nombre_resultado,
                nivel=3,
                saldo=resultado_ejercicio,  # Mantener signo para ecuación contable
            )
            balance.patrimonio.agregar_linea(linea_resultado)

        return balance

    def generar_estado_resultados(
        self,
        fecha_inicio: date,
        fecha_fin: date,
        empresa: str,
        incluir_cuentas_cero: bool = False
    ) -> EstadoResultados:
        """
        Genera el Estado de Resultados para un período.
        """
        saldos = self._obtener_saldos_directo(fecha_inicio, fecha_fin)

        estado = EstadoResultados(
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            empresa=empresa
        )

        for codigo, datos in sorted(saldos.items()):
            if not incluir_cuentas_cero and datos['saldo'] == 0:
                continue

            linea = LineaReporte(
                codigo=codigo,
                nombre=datos['nombre'],
                nivel=datos['nivel'],
                saldo=abs(datos['saldo']),
            )

            tipo = datos['tipo']
            if tipo == 'ingreso':
                estado.ingresos.append(linea)
                estado.total_ingresos += linea.saldo
            elif tipo == 'gasto':
                estado.gastos.append(linea)
                estado.total_gastos += linea.saldo

        return estado

    def generar_libro_mayor(
        self,
        cuenta_codigo: str,
        fecha_inicio: date,
        fecha_fin: date,
        empresa: str
    ) -> LibroMayor:
        """
        Genera el Libro Mayor para una cuenta específica.
        """
        # Obtener datos de la cuenta
        cuenta = self.supabase.table('cuentas_contables').select(
            'nombre, naturaleza'
        ).eq('codigo', cuenta_codigo).single().execute().data

        if not cuenta:
            raise ValueError(f"Cuenta {cuenta_codigo} no encontrada")

        naturaleza = cuenta.get('naturaleza', 'deudora')

        # Obtener movimientos de la cuenta en el período (con límite)
        movimientos = self.supabase.table('movimientos_contables').select(
            'debe, haber, concepto, asiento_id'
        ).eq(
            'cuenta_codigo', cuenta_codigo
        ).limit(2000).execute().data

        # Obtener asientos para los movimientos en lotes
        asiento_ids = list(set(m['asiento_id'] for m in movimientos))

        asientos_data = {}
        if asiento_ids:
            # Procesar en lotes de 100 para evitar límite de URL
            batch_size = 100
            for i in range(0, len(asiento_ids), batch_size):
                batch = asiento_ids[i:i + batch_size]
                asientos = self.supabase.table('asientos_contables').select(
                    'id, fecha, numero_asiento, concepto, estado'
                ).in_('id', batch).execute().data

                for a in asientos:
                    asientos_data[a['id']] = a

        libro = LibroMayor(
            cuenta_codigo=cuenta_codigo,
            cuenta_nombre=cuenta['nombre'],
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            empresa=empresa
        )

        # Calcular saldo inicial (movimientos antes del período)
        saldo_inicial = Decimal("0")
        movimientos_periodo = []

        for m in movimientos:
            asiento = asientos_data.get(m['asiento_id'])
            if not asiento or asiento.get('estado') == 'anulado':
                continue

            fecha_asiento = date.fromisoformat(asiento['fecha'])
            debe = Decimal(str(m['debe']))
            haber = Decimal(str(m['haber']))

            if fecha_asiento < fecha_inicio:
                # Movimiento anterior al período - suma al saldo inicial
                if naturaleza == 'deudora':
                    saldo_inicial += debe - haber
                else:
                    saldo_inicial += haber - debe
            elif fecha_asiento <= fecha_fin:
                # Movimiento en el período
                movimientos_periodo.append({
                    'fecha': fecha_asiento,
                    'numero_asiento': asiento['numero_asiento'],
                    'concepto': m.get('concepto') or asiento.get('concepto', ''),
                    'debe': debe,
                    'haber': haber,
                })

        libro.saldo_inicial = saldo_inicial

        # Ordenar movimientos por fecha y número de asiento
        movimientos_periodo.sort(key=lambda x: (x['fecha'], x['numero_asiento']))

        # Generar libro con saldos acumulados
        saldo_actual = saldo_inicial
        for m in movimientos_periodo:
            if naturaleza == 'deudora':
                saldo_actual += m['debe'] - m['haber']
            else:
                saldo_actual += m['haber'] - m['debe']

            libro.movimientos.append(MovimientoMayor(
                fecha=m['fecha'],
                numero_asiento=m['numero_asiento'],
                concepto=m['concepto'],
                debe=m['debe'],
                haber=m['haber'],
                saldo=saldo_actual,
            ))

            libro.total_debe += m['debe']
            libro.total_haber += m['haber']

        libro.saldo_final = saldo_actual

        return libro

    def listar_cuentas_con_movimiento(
        self,
        fecha_inicio: date,
        fecha_fin: date
    ) -> list[dict[str, Any]]:
        """Lista cuentas que tienen movimientos en el período."""
        saldos = self._obtener_saldos_directo(fecha_inicio, fecha_fin)

        cuentas = []
        for codigo, datos in sorted(saldos.items()):
            if datos['debe'] > 0 or datos['haber'] > 0:
                cuentas.append({
                    'codigo': codigo,
                    'nombre': datos['nombre'],
                    'tipo': datos['tipo'],
                    'debe': datos['debe'],
                    'haber': datos['haber'],
                    'saldo': datos['saldo'],
                })

        return cuentas
