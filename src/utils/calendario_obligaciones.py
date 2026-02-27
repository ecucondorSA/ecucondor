"""
ECUCONDOR - Motor de Calendario de Obligaciones
Sistema autónomo para cálculo de fechas de vencimiento (SRI, UAFE, SCVS).
"""

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
import calendar

class EcucondorCalendar:
    def __init__(self, ruc: str = "1391937000001"):
        self.ruc = ruc
        # El noveno dígito para ECUCONDOR es 0
        self.noveno_digito = int(ruc[8])

    def get_vencimiento_sri_mensual(self, anio: int, mes: int) -> date:
        """
        Calcula la fecha de vencimiento para IVA (104) y Retenciones (103) 
        según el noveno dígito del RUC.
        9no dígito 0 = Día 28 del mes siguiente.
        """
        dia_vencimiento = {
            1: 10, 2: 12, 3: 14, 4: 16, 5: 18,
            6: 20, 7: 22, 8: 24, 9: 26, 0: 28
        }[self.noveno_digito]
        
        # El mes de reporte se entrega el mes siguiente
        mes_venc = mes + 1
        anio_venc = anio
        if mes_venc > 12:
            mes_venc = 1
            anio_venc += 1
            
        return self._ajustar_fin_de_semana(date(anio_venc, mes_venc, dia_vencimiento))

    def get_vencimiento_uafe_resu(self, anio: int, mes: int) -> date:
        """RESU: Hasta el día 15 del mes siguiente."""
        mes_venc = mes + 1
        anio_venc = anio
        if mes_venc > 12:
            mes_venc = 1
            anio_venc += 1
        return date(anio_venc, mes_venc, 15)

    def get_vencimiento_scvs_anual(self, anio: int) -> date:
        """Estados Financieros: Hasta el 30 de abril del año siguiente."""
        return date(anio + 1, 4, 30)

    def _ajustar_fin_de_semana(self, d: date) -> date:
        """Si cae fin de semana, se traslada al siguiente día hábil."""
        if d.weekday() == 5: # Sábado
            return d + timedelta(days=2)
        if d.weekday() == 6: # Domingo
            return d + timedelta(days=1)
        return d

    def listar_obligaciones_proximas(self) -> List[Dict]:
        hoy = date.today()
        proximo_mes = hoy.month + 1
        anio_prox = hoy.year
        if proximo_mes > 12: proximo_mes = 1; anio_prox += 1

        return [
            {
                "entidad": "SRI",
                "tarea": f"Declaración IVA/Retenciones {hoy.month:02d}/{hoy.year}",
                "vencimiento": self.get_vencimiento_sri_mensual(hoy.year, hoy.month),
                "prioridad": "Alta"
            },
            {
                "entidad": "UAFE",
                "tarea": f"Reporte RESU {hoy.month:02d}/{hoy.year}",
                "vencimiento": self.get_vencimiento_uafe_resu(hoy.year, hoy.month),
                "prioridad": "Media"
            },
            {
                "entidad": "SCVS",
                "tarea": "Carga de Estados Financieros Anuales (Cierre 2025)",
                "vencimiento": self.get_vencimiento_scvs_anual(2025),
                "prioridad": "Crítica"
            }
        ]

if __name__ == "__main__":
    cal = EcucondorCalendar()
    print(f"Obligaciones para ECUCONDOR (9no dígito: {cal.noveno_digito})")
    for task in cal.listar_obligaciones_proximas():
        print(f"[{task['entidad']}] {task['tarea']} -> {task['vencimiento']} ({task['prioridad']})")
