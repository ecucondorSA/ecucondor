import sys
import os
from decimal import Decimal

# Add src to path
script_dir = os.path.dirname(__file__)
sys.path.append(os.path.join(script_dir, 'src'))

# Remove script directory from sys.path to avoid shadowing 'supabase' package
if script_dir in sys.path:
    sys.path.remove(script_dir)

from sri.iva.calculator import CalculadorIVA
from supabase import create_client

# Load env
env_vars = {}
try:
    with open('.env') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                env_vars[key] = value.strip("'\"")
except FileNotFoundError:
    print("Error: .env not found")
    sys.exit(1)

url = env_vars.get('SUPABASE_URL')
key = env_vars.get('SUPABASE_KEY')

if not url or not key:
    print("Error: SUPABASE_URL or SUPABASE_KEY not found in .env")
    sys.exit(1)

try:
    supabase = create_client(url, key)
except Exception as e:
    print(f"Error connecting to Supabase: {e}")
    sys.exit(1)

calc = CalculadorIVA(supabase)

# Company info
ruc = '1391937000001'
razon_social = 'ECUCONDOR SAS'

print(f"Calculando IVA 2025 para {razon_social} ({ruc})...")
print("-" * 95)
print(f"{ 'MES':<5} | {'VENTAS NETAS':<15} | {'IVA VENTAS':<12} | {'IVA COMPRAS':<12} | {'RETENCIONES':<12} | {'A PAGAR':<12}")
print("-" * 95)

try:
    resumen = calc.generar_resumen_anual(2025, ruc, razon_social)
    
    total_a_pagar = Decimal(0)
    total_ventas_acum = Decimal(0)

    for datos in resumen:
        # Filter only months that have passed or have data (up to Nov)
        if datos.mes > 11: continue 
        
        # Only show months with some activity or previous credit
        # if datos.total_ventas_netas == 0 and datos.iva_compras == 0 and datos.credito_tributario_anterior == 0:
        #    continue
        
        print(f"{datos.mes:<5} | "
              f"${datos.total_ventas_netas:>14,.2f} | "
              f"${datos.iva_ventas:>11,.2f} | "
              f"${datos.iva_compras:>11,.2f} | "
              f"${datos.retenciones_iva_recibidas:>11,.2f} | "
              f"${datos.iva_a_pagar:>11,.2f}")
        
        total_a_pagar += datos.iva_a_pagar
        total_ventas_acum += datos.total_ventas_netas

    print("-" * 95)
    print(f"TOTAL VENTAS 2025:      ${total_ventas_acum:,.2f}")
    print(f"TOTAL A PAGAR ACUMULADO: ${total_a_pagar:,.2f}")

except Exception as e:
    print(f"Error generating report: {e}")
    import traceback
    traceback.print_exc()
