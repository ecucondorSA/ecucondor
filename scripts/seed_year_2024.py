#!/usr/bin/env python3
"""
Script para cargar datos de ejemplo del año 2024.
Genera transacciones, facturas, honorarios y reportes.
"""

import asyncio
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from random import randint, uniform

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.supabase import get_supabase_client
from src.honorarios import get_honorarios_service
from src.ledger import get_comision_service, get_journal_service


async def crear_administrador():
    """Crea el administrador principal."""
    print("\n📋 Creando administrador...")

    service = get_honorarios_service()

    try:
        admin = await service.crear_administrador(
            tipo_identificacion="05",
            identificacion="1234567890",
            nombres="Juan Carlos",
            apellidos="Pérez González",
            email="admin@ecucondor.ec",
            telefono="0991234567",
            numero_iess="1234567890",
            banco="Banco Pichincha",
            numero_cuenta="2100123456",
            tipo_cuenta="corriente",
        )
        print(f"✅ Administrador creado: {admin.razon_social}")
        return admin.id
    except Exception as e:
        print(f"⚠️  Error (puede existir): {str(e)}")
        # Obtener existente
        db = get_supabase_client()
        result = await db.select(
            "administradores",
            filters={"identificacion": "1234567890"}
        )
        if result["data"]:
            from uuid import UUID
            return UUID(result["data"][0]["id"])
        raise


async def generar_honorarios_2024(admin_id):
    """Genera pagos de honorarios mensuales para 2024."""
    print("\n💰 Generando honorarios 2024...")

    service = get_honorarios_service()

    # Honorario mensual: $2,000
    honorario_base = Decimal("2000.00")

    for mes in range(1, 13):
        # Variar un poco el monto
        variacion = Decimal(str(uniform(-100, 200)))
        monto = honorario_base + variacion

        try:
            pago, asiento = await service.crear_pago(
                administrador_id=admin_id,
                anio=2024,
                mes=mes,
                honorario_bruto=monto,
                auto_contabilizar=True,
            )

            # Aprobar y pagar
            await service.aprobar_pago(pago.id)

            # Pagar al mes siguiente (día 5)
            if mes < 12:
                fecha_pago = date(2024, mes + 1, 5)
            else:
                fecha_pago = date(2025, 1, 5)

            await service.registrar_pago(
                pago.id,
                fecha_pago=fecha_pago,
                referencia_pago=f"TRANS-2024{mes:02d}",
            )

            print(f"✅ Mes {mes:02d}/2024: ${float(monto):,.2f} → Neto: ${float(pago.neto_pagar):,.2f}")

        except Exception as e:
            print(f"⚠️  Mes {mes}: {str(e)}")


async def generar_facturas_2024():
    """Genera facturas de ejemplo para 2024."""
    print("\n🧾 Generando facturas 2024...")

    db = get_supabase_client()
    comision_service = get_comision_service()

    # 5-10 facturas por mes
    facturas_generadas = 0

    for mes in range(1, 13):
        num_facturas = randint(5, 10)

        for i in range(num_facturas):
            # Fecha aleatoria del mes
            dia = randint(1, 28)
            fecha_emision = date(2024, mes, dia)

            # Monto aleatorio $200-$1500
            monto_alquiler = Decimal(str(round(uniform(200, 1500), 2)))
            iva = (monto_alquiler * Decimal("0.15")).quantize(Decimal("0.01"))
            total = monto_alquiler + iva

            # Cliente ficticio
            cliente_num = randint(1, 50)

            try:
                # Generar clave de acceso (simplificado)
                import hashlib
                clave_acceso = hashlib.sha256(
                    f"{fecha_emision}{total}{cliente_num}".encode()
                ).hexdigest()[:49].zfill(49)

                # Crear factura
                factura_data = {
                    "tipo_comprobante": "01",
                    "establecimiento": "001",
                    "punto_emision": "001",
                    "secuencial": str((mes - 1) * 10 + i + 1).zfill(9),
                    "clave_acceso": clave_acceso,
                    "fecha_emision": fecha_emision.isoformat(),
                    "cliente_tipo_id": "05",
                    "cliente_identificacion": f"09{cliente_num:08d}",
                    "cliente_razon_social": f"Cliente {cliente_num:03d}",
                    "importe_total": float(total),
                    "subtotal_sin_impuestos": float(monto_alquiler),
                    "subtotal_15": float(monto_alquiler),
                    "iva": float(iva),
                    "estado": "authorized",
                }

                result = await db.insert("comprobantes_electronicos", factura_data)

                if result["data"]:
                    comprobante_id = result["data"][0]["id"]

                    # Generar split de comisión (asumiendo cobro inmediato)
                    from uuid import UUID
                    split, asiento = await comision_service.procesar_cobro(
                        monto_bruto=total,
                        fecha=fecha_emision,
                        concepto=f"Factura {factura_data['secuencial']}",
                        comprobante_id=UUID(comprobante_id),
                    )

                facturas_generadas += 1

            except Exception as e:
                print(f"⚠️  Error factura {mes}/{i}: {str(e)}")

    print(f"✅ Facturas generadas: {facturas_generadas}")


async def generar_gastos_2024():
    """Genera gastos operacionales para 2024."""
    print("\n💸 Generando gastos operacionales 2024...")

    journal = get_journal_service()

    gastos = [
        ("Combustible", "5.2.05", 800, 1200),
        ("Mantenimiento", "5.2.06", 300, 800),
        ("Seguros", "5.2.07", 500, 500),
        ("Arriendo local", "5.2.01", 600, 600),
        ("Servicios básicos", "5.2.03", 80, 150),
    ]

    for mes in range(1, 13):
        for concepto, cuenta, min_monto, max_monto in gastos:
            monto = Decimal(str(round(uniform(min_monto, max_monto), 2)))
            fecha = date(2024, mes, 15)

            try:
                asiento = await journal.crear_asiento_simple(
                    fecha=fecha,
                    concepto=f"{concepto} - {mes:02d}/2024",
                    cuenta_debe=cuenta,
                    cuenta_haber="1.1.03",  # Bancos
                    monto=monto,
                    auto_contabilizar=True,
                )
                print(f"✅ {concepto} {mes:02d}/2024: ${float(monto):,.2f}")
            except Exception as e:
                print(f"⚠️  {concepto} {mes}: {str(e)}")


async def main():
    """Ejecuta el seed completo."""
    print("\n" + "=" * 60)
    print("🌱 ECUCONDOR - Seed Data 2024")
    print("=" * 60)

    input("\n⚠️  Esto generará datos de prueba para 2024. ¿Continuar? [Enter] ")

    try:
        # 1. Crear administrador
        admin_id = await crear_administrador()

        # 2. Generar honorarios
        await generar_honorarios_2024(admin_id)

        # 3. Generar facturas y comisiones
        await generar_facturas_2024()

        # 4. Generar gastos
        await generar_gastos_2024()

        print("\n" + "=" * 60)
        print("✅ Seed data 2024 completado exitosamente!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error durante seed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelado por el usuario")
        sys.exit(1)
