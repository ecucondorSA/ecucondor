"""
ECUCONDOR - Servicio de Liquidaciones de Compra
Gestión de liquidaciones para compra de criptomonedas a personas naturales.

Modelo de Negocio:
- ECUCONDOR es intermediario de criptomonedas
- Compra cripto a vendedores (Paula) - emite Liquidación de Compra (03)
- Vende cripto a compradores (Luis) - emite Factura (01) por comisión
- Criptomonedas: Tarifa 0% / Exentas de IVA
- Comisión: 1.5% cobrada al comprador
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import structlog

from src.db.supabase import get_supabase_client

logger = structlog.get_logger(__name__)


@dataclass
class LiquidacionCripto:
    """Datos de una liquidación de compra de criptomonedas."""
    # Vendedor (persona natural)
    vendedor_tipo_id: str  # 05 = Cédula
    vendedor_identificacion: str
    vendedor_nombre: str

    # Transacción
    fecha_emision: date
    concepto: str
    monto_cripto: Decimal  # Monto en USD de la cripto comprada

    # Tipo de cripto (para descripción)
    tipo_cripto: str = "USDT"  # USDT, BTC, ETH, etc.

    # Retención IR (opcional - por defecto 0 para cripto P2P)
    aplica_retencion_ir: bool = False
    porcentaje_retencion_ir: Decimal = Decimal("0")

    # Contabilización
    cuenta_cripto: str = "1.1.1.04"  # Activo: Criptomonedas
    auto_contabilizar: bool = True


@dataclass
class FacturaComision:
    """Datos para facturar comisión al comprador."""
    # Comprador
    comprador_tipo_id: str  # 05 = Cédula, 04 = RUC
    comprador_identificacion: str
    comprador_nombre: str

    # Transacción
    fecha_emision: date
    monto_transaccion: Decimal  # Monto total de la transacción
    porcentaje_comision: Decimal = Decimal("1.5")  # 1.5%

    # IVA 15% sobre la comisión
    # Comisión = monto * 1.5% = base_imponible
    # IVA = base_imponible * 15%
    # Total factura = base_imponible + IVA


class LiquidacionService:
    """
    Servicio para gestionar liquidaciones de compra de criptomonedas
    y facturas de comisión por intermediación.
    """

    def __init__(self, supabase=None):
        self.supabase = supabase or get_supabase_client()

    async def crear_liquidacion_cripto(self, data: LiquidacionCripto) -> dict:
        """
        Crea una liquidación de compra para criptomonedas.

        Liquidación de Compra (tipo 03):
        - Se emite cuando compramos a persona natural que no puede facturar
        - Criptomonedas son exentas de IVA
        - El valor a pagar = monto_cripto (sin retenciones por ser exento)

        Returns:
            dict con la liquidación creada y sus detalles
        """
        try:
            # 1. Buscar o crear proveedor (vendedor)
            proveedor = self.supabase.table('proveedores').select('id').eq(
                'identificacion', data.vendedor_identificacion
            ).execute()

            proveedor_id = None
            if proveedor.data:
                proveedor_id = proveedor.data[0]['id']
            else:
                nuevo = self.supabase.table('proveedores').insert({
                    'tipo_identificacion': data.vendedor_tipo_id,
                    'identificacion': data.vendedor_identificacion,
                    'razon_social': data.vendedor_nombre,
                    'categoria': 'cripto_vendedor',
                    'activo': True
                }).execute()
                if nuevo.data:
                    proveedor_id = nuevo.data[0]['id']

            # 2. Obtener siguiente secuencial para Liquidación (03)
            secuencial = await self._obtener_secuencial('03')

            # 3. Calcular retención IR (si aplica)
            retencion_ir = Decimal("0")
            if data.aplica_retencion_ir:
                retencion_ir = data.monto_cripto * data.porcentaje_retencion_ir / 100

            valor_a_pagar = data.monto_cripto - retencion_ir

            # 4. Crear registro en facturas_recibidas
            liquidacion_data = {
                'proveedor_id': str(proveedor_id) if proveedor_id else None,
                'proveedor_tipo_id': data.vendedor_tipo_id,
                'proveedor_identificacion': data.vendedor_identificacion,
                'proveedor_razon_social': data.vendedor_nombre,
                'tipo_comprobante': '03',  # Liquidación de Compra
                'establecimiento': '001',
                'punto_emision': '001',
                'secuencial': secuencial,
                'fecha_emision': data.fecha_emision.isoformat(),

                # Montos - cripto es exento
                'subtotal_sin_impuestos': float(data.monto_cripto),
                'subtotal_15': 0.0,  # No hay IVA
                'subtotal_0': 0.0,
                'subtotal_no_objeto': 0.0,
                'subtotal_exento': float(data.monto_cripto),  # Cripto = Exento
                'iva': 0.0,
                'total': float(data.monto_cripto),

                # Clasificación
                'tipo_gasto': 'costo_ventas',
                'genera_credito_tributario': False,  # No hay IVA que acreditar
                'cuenta_gasto': data.cuenta_cripto,

                # Retenciones
                'aplica_retencion_renta': data.aplica_retencion_ir,
                'porcentaje_retencion_renta': float(data.porcentaje_retencion_ir),
                'retencion_renta': float(retencion_ir),
                'aplica_retencion_iva': False,  # No hay IVA
                'porcentaje_retencion_iva': 0.0,
                'retencion_iva': 0.0,

                'concepto': f"{data.concepto} - {data.tipo_cripto}",
                'estado': 'pendiente'
            }

            result = self.supabase.table('facturas_recibidas').insert(liquidacion_data).execute()

            if not result.data:
                raise Exception("No se pudo crear la liquidación")

            liquidacion = result.data[0]

            # 5. Contabilizar si está habilitado
            if data.auto_contabilizar:
                await self._contabilizar_liquidacion_cripto(
                    liquidacion_id=liquidacion['id'],
                    monto=data.monto_cripto,
                    cuenta_cripto=data.cuenta_cripto,
                    retencion_ir=retencion_ir,
                    vendedor=data.vendedor_nombre,
                    fecha=data.fecha_emision
                )

                # Actualizar estado
                self.supabase.table('facturas_recibidas').update({
                    'estado': 'contabilizada'
                }).eq('id', liquidacion['id']).execute()

            logger.info(
                "Liquidación cripto creada",
                numero=f"001-001-{secuencial}",
                vendedor=data.vendedor_nombre,
                monto=float(data.monto_cripto)
            )

            return {
                "success": True,
                "liquidacion": liquidacion,
                "numero": f"001-001-{secuencial}",
                "vendedor": data.vendedor_nombre,
                "monto_cripto": float(data.monto_cripto),
                "retencion_ir": float(retencion_ir),
                "valor_a_pagar": float(valor_a_pagar),
                "contabilizada": data.auto_contabilizar
            }

        except Exception as e:
            logger.error(f"Error creando liquidación: {e}")
            return {"success": False, "error": str(e)}

    async def crear_factura_comision(self, data: FacturaComision) -> dict:
        """
        Crea una factura por la comisión de intermediación.

        Factura (tipo 01):
        - Se emite al comprador (Luis) por el servicio de intermediación
        - Base: monto_transaccion * porcentaje_comision
        - IVA 15% sobre la comisión

        Returns:
            dict con la factura creada y sus detalles
        """
        try:
            # Calcular comisión
            comision_base = data.monto_transaccion * data.porcentaje_comision / 100
            iva_comision = comision_base * Decimal("0.15")
            total_factura = comision_base + iva_comision

            # Buscar o crear cliente (comprador)
            cliente = self.supabase.table('clientes').select('id').eq(
                'identificacion', data.comprador_identificacion
            ).execute()

            cliente_id = None
            if cliente.data:
                cliente_id = cliente.data[0]['id']
            else:
                nuevo = self.supabase.table('clientes').insert({
                    'tipo_identificacion': data.comprador_tipo_id,
                    'identificacion': data.comprador_identificacion,
                    'razon_social': data.comprador_nombre,
                    'email': '',
                    'activo': True
                }).execute()
                if nuevo.data:
                    cliente_id = nuevo.data[0]['id']

            # Obtener secuencial para Factura (01)
            secuencial = await self._obtener_secuencial('01')

            # Crear comprobante electrónico
            factura_data = {
                'cliente_id': str(cliente_id) if cliente_id else None,
                'tipo_identificacion_comprador': data.comprador_tipo_id,
                'identificacion_comprador': data.comprador_identificacion,
                'razon_social_comprador': data.comprador_nombre,
                'tipo_comprobante': '01',  # Factura
                'establecimiento': '001',
                'punto_emision': '001',
                'secuencial': secuencial,
                'fecha_emision': data.fecha_emision.isoformat(),

                # Montos
                'subtotal_sin_impuestos': float(comision_base),
                'subtotal_15': float(comision_base),  # Base gravada 15%
                'subtotal_0': 0.0,
                'total_descuento': 0.0,
                'iva': float(iva_comision),
                'total': float(total_factura),
                'propina': 0.0,

                'estado': 'borrador',
                'ambiente': 'produccion'
            }

            result = self.supabase.table('comprobantes_electronicos').insert(factura_data).execute()

            if not result.data:
                raise Exception("No se pudo crear la factura")

            factura = result.data[0]

            # Crear detalle de la factura
            detalle_data = {
                'comprobante_id': factura['id'],
                'codigo_principal': 'SERV-INT-001',
                'codigo_auxiliar': '',
                'descripcion': f'Comisión por intermediación cripto ({data.porcentaje_comision}%)',
                'cantidad': 1,
                'precio_unitario': float(comision_base),
                'descuento': 0.0,
                'precio_total_sin_impuesto': float(comision_base),
                'tipo_iva': 'gravado_15',
                'tarifa_iva': 15.0,
                'valor_iva': float(iva_comision)
            }

            self.supabase.table('comprobante_detalles').insert(detalle_data).execute()

            logger.info(
                "Factura comisión creada",
                numero=f"001-001-{secuencial}",
                comprador=data.comprador_nombre,
                comision=float(comision_base),
                iva=float(iva_comision),
                total=float(total_factura)
            )

            return {
                "success": True,
                "factura": factura,
                "numero": f"001-001-{secuencial}",
                "comprador": data.comprador_nombre,
                "monto_transaccion": float(data.monto_transaccion),
                "porcentaje_comision": float(data.porcentaje_comision),
                "comision_base": float(comision_base),
                "iva": float(iva_comision),
                "total": float(total_factura)
            }

        except Exception as e:
            logger.error(f"Error creando factura comisión: {e}")
            return {"success": False, "error": str(e)}

    async def procesar_transaccion_cripto(
        self,
        vendedor_cedula: str,
        vendedor_nombre: str,
        comprador_cedula: str,
        comprador_nombre: str,
        monto_cripto: Decimal,
        tipo_cripto: str = "USDT",
        fecha: Optional[date] = None,
        concepto: str = "Compra de criptomonedas"
    ) -> dict:
        """
        Procesa una transacción completa de intermediación cripto.

        1. Crea Liquidación de Compra a vendedor (Paula)
        2. Crea Factura de Comisión a comprador (Luis)

        Returns:
            dict con ambos documentos y resumen
        """
        fecha = fecha or date.today()

        # 1. Liquidación a vendedor
        liquidacion_data = LiquidacionCripto(
            vendedor_tipo_id="05",  # Cédula
            vendedor_identificacion=vendedor_cedula,
            vendedor_nombre=vendedor_nombre,
            fecha_emision=fecha,
            concepto=concepto,
            monto_cripto=monto_cripto,
            tipo_cripto=tipo_cripto,
            aplica_retencion_ir=False,  # P2P sin retención
            auto_contabilizar=True
        )
        liquidacion = await self.crear_liquidacion_cripto(liquidacion_data)

        if not liquidacion.get('success'):
            return {
                "success": False,
                "error": f"Error en liquidación: {liquidacion.get('error')}"
            }

        # 2. Factura comisión a comprador
        factura_data = FacturaComision(
            comprador_tipo_id="05",  # Cédula
            comprador_identificacion=comprador_cedula,
            comprador_nombre=comprador_nombre,
            fecha_emision=fecha,
            monto_transaccion=monto_cripto,
            porcentaje_comision=Decimal("1.5")  # 1.5%
        )
        factura = await self.crear_factura_comision(factura_data)

        if not factura.get('success'):
            return {
                "success": False,
                "error": f"Error en factura: {factura.get('error')}",
                "liquidacion": liquidacion
            }

        # Calcular resumen
        comision_total = factura.get('total', 0)

        return {
            "success": True,
            "transaccion": {
                "fecha": fecha.isoformat(),
                "tipo_cripto": tipo_cripto,
                "monto_cripto": float(monto_cripto),
                "comision": float(factura.get('comision_base', 0)),
                "iva_comision": float(factura.get('iva', 0)),
                "total_comprador": float(monto_cripto) + float(comision_total),
                "pago_vendedor": float(monto_cripto),
                "ganancia_ecucondor": float(comision_total)
            },
            "documentos": {
                "liquidacion": liquidacion,
                "factura": factura
            },
            "resumen_sri": {
                "iva_ventas": float(factura.get('iva', 0)),
                "iva_compras": 0.0,  # Cripto exento
                "iva_a_pagar": float(factura.get('iva', 0))
            }
        }

    async def listar_liquidaciones(
        self,
        anio: int,
        mes: int,
        limit: int = 100
    ) -> dict:
        """Lista liquidaciones de compra del período."""
        try:
            fecha_inicio = date(anio, mes, 1)
            if mes == 12:
                fecha_fin = date(anio + 1, 1, 1)
            else:
                fecha_fin = date(anio, mes + 1, 1)

            result = self.supabase.table('facturas_recibidas').select('*').eq(
                'tipo_comprobante', '03'
            ).gte(
                'fecha_emision', fecha_inicio.isoformat()
            ).lt(
                'fecha_emision', fecha_fin.isoformat()
            ).order('fecha_emision', desc=True).limit(limit).execute()

            # Calcular totales
            total_monto = sum(Decimal(str(l['total'])) for l in result.data)

            return {
                "liquidaciones": result.data,
                "total": len(result.data),
                "monto_total": float(total_monto),
                "periodo": f"{mes:02d}/{anio}"
            }

        except Exception as e:
            logger.error(f"Error listando liquidaciones: {e}")
            return {"liquidaciones": [], "total": 0, "error": str(e)}

    async def _obtener_secuencial(self, tipo_comprobante: str) -> str:
        """Obtiene el siguiente secuencial para el tipo de comprobante."""
        try:
            # Consultar último secuencial usado
            result = self.supabase.table('facturas_recibidas').select(
                'secuencial'
            ).eq(
                'tipo_comprobante', tipo_comprobante
            ).order('created_at', desc=True).limit(1).execute()

            if result.data:
                ultimo = int(result.data[0]['secuencial'])
                return str(ultimo + 1).zfill(9)

            return "000000001"

        except Exception:
            return "000000001"

    async def _contabilizar_liquidacion_cripto(
        self,
        liquidacion_id: str,
        monto: Decimal,
        cuenta_cripto: str,
        retencion_ir: Decimal,
        vendedor: str,
        fecha: date
    ):
        """
        Genera asiento contable para liquidación de compra de cripto.

        Asiento:
        - Debe: Criptomonedas (activo) = monto
        - Haber: Caja/Banco = monto - retención
        - Haber: Ret. IR por Pagar = retención (si aplica)
        """
        try:
            valor_a_pagar = monto - retencion_ir

            # Crear movimiento contable
            movimiento = self.supabase.table('movimientos_contables').insert({
                'fecha': fecha.isoformat(),
                'tipo_movimiento': 'liquidacion_compra',
                'numero_documento': liquidacion_id[:8],
                'descripcion': f'Compra cripto a {vendedor}',
                'referencia': f'LIQ-{liquidacion_id[:8]}',
                'estado': 'contabilizado'
            }).execute()

            if not movimiento.data:
                return

            mov_id = movimiento.data[0]['id']

            lineas = [
                # Debe: Criptomonedas
                {
                    'movimiento_id': mov_id,
                    'cuenta_codigo': cuenta_cripto,
                    'descripcion': f'Compra {vendedor}',
                    'debe': float(monto),
                    'haber': 0.0
                },
                # Haber: Banco (pago)
                {
                    'movimiento_id': mov_id,
                    'cuenta_codigo': '1.1.1.02',  # Bancos
                    'descripcion': f'Pago a {vendedor}',
                    'debe': 0.0,
                    'haber': float(valor_a_pagar)
                }
            ]

            # Si hay retención IR
            if retencion_ir > 0:
                lineas.append({
                    'movimiento_id': mov_id,
                    'cuenta_codigo': '2.1.3.03',  # Ret. IR por Pagar
                    'descripcion': f'Ret. IR {vendedor}',
                    'debe': 0.0,
                    'haber': float(retencion_ir)
                })

            self.supabase.table('movimiento_lineas').insert(lineas).execute()

            logger.info(f"Asiento contable creado para liquidación {liquidacion_id[:8]}")

        except Exception as e:
            logger.error(f"Error contabilizando liquidación: {e}")
