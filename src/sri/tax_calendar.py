"""
Servicio de Calendario Tributario SRI.
Calcula fechas de vencimiento según el noveno dígito del RUC.
Integrado con base de datos para seguimiento de cumplimiento.
"""

from datetime import date, timedelta
from typing import List, Dict, Optional, Any
import calendar
import structlog

logger = structlog.get_logger(__name__)


class TaxCalendar:
    """Calculadora de vencimientos tributarios."""

    # Mapeo de días límite por noveno dígito
    DEADLINE_MAPPING = {
        1: 10, 2: 12, 3: 14, 4: 16, 5: 18,
        6: 20, 7: 22, 8: 24, 9: 26, 0: 28
    }

    # Nombres de meses en español
    MESES = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ]

    def __init__(self, ruc: str, supabase_client=None):
        self.ruc = ruc
        self.noveno_digito = int(ruc[8]) if len(ruc) >= 9 else 0
        self.supabase = supabase_client

    def get_deadline_day(self) -> int:
        """
        Retorna el día máximo de pago según el noveno dígito.
        1 -> 10, 2 -> 12, ..., 9 -> 26, 0 -> 28
        """
        return self.DEADLINE_MAPPING.get(self.noveno_digito, 28)

    def get_deadline_date(self, year: int, month: int) -> date:
        """
        Calcula la fecha de vencimiento ajustada para un mes específico.
        Considera fines de semana y el último día del mes.
        """
        deadline_day = self.get_deadline_day()

        # Ajustar al último día del mes si es necesario
        ultimo_dia = calendar.monthrange(year, month)[1]
        deadline_day = min(deadline_day, ultimo_dia)

        deadline_date = date(year, month, deadline_day)

        # Ajustar si cae en fin de semana (trasladar al siguiente día hábil)
        if deadline_date.weekday() == 5:  # Sábado
            deadline_date += timedelta(days=2)
        elif deadline_date.weekday() == 6:  # Domingo
            deadline_date += timedelta(days=1)

        return deadline_date

    def get_obligations(self, year: int, month: int) -> List[Dict]:
        """
        Retorna las obligaciones para un mes específico.
        El mes se refiere al periodo de DECLARACIÓN, no al periodo declarado.
        """
        deadline_date = self.get_deadline_date(year, month)
        formatted_date = deadline_date.strftime("%Y-%m-%d")
        display_date = deadline_date.strftime("%d de %B")
        prev_month_name = self._get_prev_month_name(month)
        days_remaining = (deadline_date - date.today()).days

        obligations = [
            {
                "codigo": "IVA_MENSUAL",
                "nombre": "Declaración de IVA Mensual",
                "descripcion": f"Formulario 104 - {prev_month_name}",
                "vencimiento": formatted_date,
                "display_date": display_date,
                "tipo": "IVA",
                "formulario": "104",
                "prioridad": "alta",
                "dias_restantes": days_remaining,
                "alerta": days_remaining <= 5
            },
            {
                "codigo": "RET_FUENTE",
                "nombre": "Retenciones en la Fuente",
                "descripcion": f"Formulario 103 - {prev_month_name}",
                "vencimiento": formatted_date,
                "display_date": display_date,
                "tipo": "Retención",
                "formulario": "103",
                "prioridad": "alta",
                "dias_restantes": days_remaining,
                "alerta": days_remaining <= 5
            },
            {
                "codigo": "ATS",
                "nombre": "Anexo Transaccional Simplificado",
                "descripcion": f"ATS - {prev_month_name}",
                "vencimiento": formatted_date,
                "display_date": display_date,
                "tipo": "ATS",
                "formulario": "ATS",
                "prioridad": "media",
                "dias_restantes": days_remaining,
                "alerta": days_remaining <= 5
            }
        ]

        return obligations

    def get_upcoming_obligations(self, days_ahead: int = 60) -> List[Dict]:
        """
        Obtiene todas las obligaciones próximas en los siguientes N días.
        Intenta usar la base de datos si está disponible, sino calcula localmente.
        """
        if self.supabase:
            try:
                result = self.supabase.rpc(
                    'obtener_proximas_obligaciones',
                    {'p_ruc': self.ruc, 'p_dias_adelante': days_ahead}
                ).execute()
                if result.data:
                    return self._format_db_obligations(result.data)
            except Exception as e:
                logger.warning("Error obteniendo obligaciones de DB, usando cálculo local", error=str(e))

        # Fallback: cálculo local
        return self._calculate_local_obligations(days_ahead)

    def _calculate_local_obligations(self, days_ahead: int) -> List[Dict]:
        """Calcula obligaciones localmente sin usar la base de datos."""
        today = date.today()
        target_date = today + timedelta(days=days_ahead)
        obligations = []

        current = date(today.year, today.month, 1)
        while current <= target_date:
            month_obligations = self.get_obligations(current.year, current.month)
            for obl in month_obligations:
                venc_date = date.fromisoformat(obl['vencimiento'])
                if today <= venc_date <= target_date:
                    obl['periodo_anio'] = current.year
                    obl['periodo_mes'] = current.month - 1 if current.month > 1 else 12
                    obligations.append(obl)

            # Siguiente mes
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)

        return sorted(obligations, key=lambda x: x['vencimiento'])

    def _format_db_obligations(self, db_data: List[Dict]) -> List[Dict]:
        """Formatea los datos de la base de datos al formato esperado."""
        formatted = []
        for row in db_data:
            venc_date = row.get('fecha_vencimiento')
            if isinstance(venc_date, str):
                venc_date = date.fromisoformat(venc_date)

            formatted.append({
                "codigo": row.get('tipo_codigo'),
                "nombre": row.get('tipo_nombre'),
                "descripcion": f"Formulario {row.get('formulario', '')} - Período {row.get('periodo_mes')}/{row.get('periodo_anio')}",
                "vencimiento": str(row.get('fecha_vencimiento')),
                "display_date": venc_date.strftime("%d de %B") if isinstance(venc_date, date) else str(venc_date),
                "tipo": row.get('tipo_codigo', '').split('_')[0],
                "formulario": row.get('formulario'),
                "prioridad": row.get('prioridad', 'media'),
                "dias_restantes": row.get('dias_restantes', 0),
                "alerta": row.get('alerta', False),
                "estado": row.get('estado', 'pendiente'),
                "periodo_anio": row.get('periodo_anio'),
                "periodo_mes": row.get('periodo_mes')
            })
        return formatted

    def get_calendar_widget_data(self) -> Dict[str, Any]:
        """
        Obtiene los datos para el widget del dashboard.
        """
        if self.supabase:
            try:
                result = self.supabase.rpc(
                    'get_calendario_widget',
                    {'p_ruc': self.ruc}
                ).execute()
                if result.data:
                    return result.data
            except Exception as e:
                logger.warning("Error obteniendo widget data de DB", error=str(e))

        # Fallback: construir datos localmente
        upcoming = self.get_upcoming_obligations(30)
        alertas = sum(1 for o in upcoming if o.get('alerta', False))

        return {
            "proximas_obligaciones": upcoming[:5],
            "alertas": alertas,
            "vencidas": 0,
            "resumen_mes_actual": {
                "total_pendientes": len(upcoming),
                "total_cumplidas": 0,
                "total_vencidas": 0
            }
        }

    def mark_obligation_completed(
        self,
        tipo_codigo: str,
        anio: int,
        mes: int,
        numero_formulario: Optional[str] = None,
        monto_declarado: Optional[float] = None,
        monto_pagado: Optional[float] = None
    ) -> bool:
        """
        Marca una obligación como cumplida en la base de datos.
        """
        if not self.supabase:
            logger.warning("No hay cliente Supabase para registrar cumplimiento")
            return False

        try:
            result = self.supabase.rpc(
                'registrar_cumplimiento_obligacion',
                {
                    'p_tipo_codigo': tipo_codigo,
                    'p_anio': anio,
                    'p_mes': mes,
                    'p_numero_formulario': numero_formulario,
                    'p_monto_declarado': monto_declarado,
                    'p_monto_pagado': monto_pagado
                }
            ).execute()
            return result.data is not None
        except Exception as e:
            logger.error("Error registrando cumplimiento", error=str(e))
            return False

    def _get_prev_month_name(self, current_month: int) -> str:
        """Retorna el nombre del mes anterior."""
        prev_month = current_month - 1 if current_month > 1 else 12
        return self.MESES[prev_month - 1]

    def _get_month_name(self, month: int) -> str:
        """Retorna el nombre del mes."""
        return self.MESES[month - 1] if 1 <= month <= 12 else ""
