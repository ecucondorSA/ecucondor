import sys
import os
from decimal import Decimal

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from sri.ats.builder import ATSBuilder
from sri.ats.models import ATS, DetalleCompra, SustentoTributario

# Create dummy ATS data
ats = ATS(
    tipo_id_informante="R",
    id_informante="1790011223001",
    razon_social="EMPRESA DE PRUEBA",
    anio=2024,
    mes=1,
    num_estab_ruc="001",
    total_ventas=Decimal("100.00"),
    codigo_operativo="IVA",
    compras=[
        DetalleCompra(
            cod_sustento=SustentoTributario.COSTO_GASTO_NO_CREDITO_IVA,
            tp_id_prov="05",
            id_prov="1712345678",
            tipo_comprobante="03",
            tipo_prov="01",
            deno_prov="PROVEEDOR PRUEBA",
            parte_relacionada="NO",
            fecha_registro="01/01/2024",
            establecimiento="001",
            punto_emision="001",
            secuencial="000000001",
            fecha_emision="01/01/2024",
            autorizacion="1234567890",
            base_no_grava_iva=Decimal("0.00"),
            base_imponible_0=Decimal("0.00"),
            base_imponible_15=Decimal("0.00"),
            base_exenta=Decimal("100.00"),
            monto_iva=Decimal("0.00"),
            monto_ice=Decimal("0.00"),
            formas_pago=["01"]
        )
    ]
)

# Build XML
builder = ATSBuilder()
xml = builder.build(ats)

# Check for correct structure
expected_snippet_ventas = "<ventasEstablecimiento><ventaEst><codEstab>001</codEstab>"
expected_snippet_compras = "<compras><detalleCompras><codSustento>02</codSustento>"

if expected_snippet_compras in xml.replace("\n", "").replace(" ", ""):
    print("SUCCESS: XML structure is correct (Compras included).")
    print(xml)
else:
    print("FAILURE: XML structure is incorrect (Missing Compras).")
    print(xml)
