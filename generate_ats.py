import sys
import os
from datetime import date
from decimal import Decimal

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from sri.ats.builder import ATSBuilder
from sri.ats.models import ATS, DetalleVenta, DetalleCompra, SustentoTributario
from supabase import create_client, Client

# Load .env manually
env_vars = {}
try:
    with open('.env') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                env_vars[key] = value.strip('\"\'')
except FileNotFoundError:
    print("Error: .env file not found")
    exit(1)

url = env_vars.get('SUPABASE_URL')
key = env_vars.get('SUPABASE_KEY')
supabase: Client = create_client(url, key)

def generate_ats(anio: int, mes: int):
    print(f"Generando ATS para {mes}/{anio}...")

    # Fetch company info
    try:
        company = supabase.table('company_info').select('*').single().execute().data
    except Exception as e:
        print(f"Error fetching company info: {e}")
        company = {'ruc': '9999999999001', 'razon_social': 'EMPRESA DEFAULT'}

    # Fetch sales (comprobantes_electronicos)
    start_date = date(anio, mes, 1)
    if mes == 12:
        end_date = date(anio + 1, 1, 1)
    else:
        end_date = date(anio, mes + 1, 1)

    try:
        facturas = supabase.table('comprobantes_electronicos').select('*').eq(
            'tipo_comprobante', '01'
        ).gte('fecha_emision', start_date.isoformat()).lt(
            'fecha_emision', end_date.isoformat()
        ).eq('estado', 'authorized').execute().data
    except Exception as e:
        print(f"Error fetching invoices: {e}")
        facturas = []

    # Fetch purchases (facturas_recibidas) including Liquidaciones de Compra
    try:
        compras_db = supabase.table('facturas_recibidas').select('*').gte(
            'fecha_emision', start_date.isoformat()
        ).lt(
            'fecha_emision', end_date.isoformat()
        ).execute().data
    except Exception as e:
        print(f"Error fetching purchases: {e}")
        compras_db = []

    ventas = []
    total_ventas = Decimal("0")

    for f in facturas:
        subtotal = Decimal(str(f.get('subtotal_sin_impuestos', 0))) + Decimal(str(f.get('subtotal_12', 0))) + Decimal(str(f.get('subtotal_15', 0)))
        iva = Decimal(str(f.get('iva', 0)))
        total = Decimal(str(f.get('importe_total', 0)))
        
        total_ventas += subtotal

        detalle = DetalleVenta(
            tipo_id_cliente=f.get('cliente_tipo_id', '05'),
            id_cliente=f.get('cliente_identificacion', '9999999999999'),
            parte_relacionada="NO",
            tipo_comprobante="18", # Factura
            tipo_emision="E", # Electronica
            numero_comprobantes=1,
            base_no_grava_iva=Decimal(str(f.get('subtotal_no_objeto', 0))),
            base_imponible_0=Decimal(str(f.get('subtotal_0', 0))),
            base_imponible_15=Decimal(str(f.get('subtotal_15', 0))), # Asumiendo 15% actual
            monto_iva=iva,
            monto_ice=Decimal("0"),
            valor_ret_iva=Decimal("0"),
            valor_ret_renta=Decimal("0"),
            formas_pago=["20"] # Otros con utilizacion del sistema financiero
        )
        ventas.append(detalle)

    compras = []
    for c in compras_db:
        # Formatear fecha dd/mm/aaaa
        fecha_iso = c.get('fecha_emision')
        fecha_obj = date.fromisoformat(fecha_iso)
        fecha_fmt = fecha_obj.strftime("%d/%m/%Y")

        detalle = DetalleCompra(
            cod_sustento=SustentoTributario.COSTO_GASTO_NO_CREDITO_IVA, # Asumimos 02 para liquidaciones exentas
            tp_id_prov=c.get('proveedor_tipo_id', '05'),
            id_prov=c.get('proveedor_identificacion', '9999999999999'),
            tipo_comprobante=c.get('tipo_comprobante', '03'), # Liquidacion de compra
            tipo_prov='01', # Persona Natural
            deno_prov=c.get('proveedor_razon_social', ''),
            parte_relacionada="NO",
            fecha_registro=fecha_fmt,
            establecimiento=c.get('establecimiento', '001'),
            punto_emision=c.get('punto_emision', '001'),
            secuencial=c.get('secuencial', '000000000'),
            fecha_emision=fecha_fmt,
            autorizacion=c.get('autorizacion', '9999999999'), # Si es física usar 10 dígitos, electrónica 49
            base_no_grava_iva=Decimal(str(c.get('subtotal_no_objeto', 0))),
            base_imponible_0=Decimal(str(c.get('subtotal_0', 0))),
            base_imponible_15=Decimal(str(c.get('subtotal_15', 0))),
            base_exenta=Decimal(str(c.get('subtotal_exento', 0))),
            monto_iva=Decimal(str(c.get('iva', 0))),
            monto_ice=Decimal(str(c.get('ice', 0))),
            formas_pago=["01"] # Sin utilizacion del sistema financiero (o ajustar según lógica)
        )
        compras.append(detalle)

    ats = ATS(
        tipo_id_informante="R",
        id_informante=company.get('ruc', '9999999999001'),
        razon_social=company.get('razon_social', 'EMPRESA DEFAULT'),
        anio=anio,
        mes=mes,
        num_estab_ruc="001",
        total_ventas=total_ventas,
        codigo_operativo="IVA",
        ventas=ventas,
        compras=compras
    )

    builder = ATSBuilder()
    xml = builder.build(ats)
    
    filename = f"ATS_{mes:02d}_{anio}.xml"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(xml)
        f.flush()  # Asegurar que se escriba en disco
        os.fsync(f.fileno())  # Forzar sincronización del sistema de archivos
    
    print(f"ATS generado exitosamente: {filename}")
    print(xml)

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        anio = int(sys.argv[1])
        mes = int(sys.argv[2])
    else:
        anio = 2025
        mes = 11
    
    generate_ats(anio, mes)
