import os
import sys
from datetime import date, datetime
from decimal import Decimal
from collections import defaultdict

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

# Remove current directory from sys.path to avoid shadowing 'supabase' package with local folder
# This is necessary because there is a 'supabase' folder in the root
current_dir = os.getcwd()
if current_dir in sys.path:
    sys.path.remove(current_dir)
if '' in sys.path:
    sys.path.remove('')

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

if not url or not key:
    print("Error: SUPABASE_URL or SUPABASE_KEY not found in .env")
    exit(1)

supabase: Client = create_client(url, key)

def format_currency(amount):
    return f"${amount:,.2f}"

def main():
    print("--- ECUCONDOR FINANCIAL REPORT (Nov 2024 - Nov 2025) ---")
    
    start_date = "2024-11-01"
    end_date = "2025-11-30" # Covers up to end of Nov 2025
    
    # 1. TOTAL VOLUME (Sales)
    print(f"\n1. Calculating Total Volume (Sales) from {start_date} to {end_date}...")
    try:
        # Fetch all authorized invoices in range
        response = supabase.table('comprobantes_electronicos').select('importe_total, fecha_emision').eq(
            'tipo_comprobante', '01' # Factura
        ).eq('estado', 'authorized').gte(
            'fecha_emision', start_date
        ).lte(
            'fecha_emision', end_date
        ).execute()
        
        invoices = response.data
        total_volume = sum(Decimal(str(inv['importe_total'])) for inv in invoices)
        count_invoices = len(invoices)
        
        print(f"   Total Invoices: {count_invoices}")
        print(f"   Total Volume: {format_currency(total_volume)}")
        
        # 2. COMMISSIONS (Estimated 1.5%)
        commissions = total_volume * Decimal("0.015")
        print(f"\n2. Estimated Commissions (1.5%): {format_currency(commissions)}")
        
    except Exception as e:
        print(f"   Error calculating volume: {e}")

    # 3. EXPENSES (From Ledger or Bank Transactions)
    print(f"\n3. Analyzing Major Expenses...")
    try:
        # Check Bank Debits (Real cash flow out)
        print("   Analyzing Bank Debits (Cash Flow Out)...")
        bank_debits = supabase.table('transacciones_bancarias').select('monto, descripcion_original, categoria_sugerida').eq('tipo', 'debito').gte('fecha', start_date).lte('fecha', end_date).execute()
        
        if bank_debits.data:
            total_debits = sum(Decimal(str(tx['monto'])) for tx in bank_debits.data)
            print(f"   Total Bank Debits: {format_currency(total_debits)}")
            
            expenses_by_category = defaultdict(Decimal)
            for tx in bank_debits.data:
                cat = tx.get('categoria_sugerida') or 'Uncategorized'
                expenses_by_category[cat] += Decimal(str(tx['monto']))
                
            print("   Top Expenses by Bank Category:")
            for cat, amount in sorted(expenses_by_category.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"     - {cat}: {format_currency(amount)}")
        else:
            print("   No bank debits found.")

        # Check Ledger (Accounting)
        print("\n   Analyzing Ledger Expenses (Accounting)...")
        # First get expense accounts
        accounts_resp = supabase.table('cuentas_contables').select('codigo, nombre').ilike('codigo', '5%').execute()
        expense_accounts = {acc['codigo']: acc['nombre'] for acc in accounts_resp.data}
        
        if expense_accounts:
            # Fetch asientos in range
            asientos_resp = supabase.table('asientos_contables').select('id').gte('fecha', start_date).lte('fecha', end_date).eq('estado', 'contabilizado').execute()
            asiento_ids = [a['id'] for a in asientos_resp.data]
            
            if asiento_ids:
                # Chunking if too many
                chunk_size = 100
                total_expenses = defaultdict(Decimal)
                
                for i in range(0, len(asiento_ids), chunk_size):
                    chunk = asiento_ids[i:i+chunk_size]
                    movements_resp = supabase.table('movimientos_contables').select('cuenta_codigo, debe').in_('asiento_id', chunk).execute()
                    
                    for mov in movements_resp.data:
                        code = mov['cuenta_codigo']
                        if code.startswith('5'): # Expense
                            name = expense_accounts.get(code, 'Unknown Expense')
                            total_expenses[name] += Decimal(str(mov['debe']))
                
                if total_expenses:
                    print("   Top Expenses by Ledger Account:")
                    for name, amount in sorted(total_expenses.items(), key=lambda x: x[1], reverse=True)[:5]:
                        print(f"     - {name}: {format_currency(amount)}")
                else:
                    print("   No expense movements found in posted ledger entries.")
            else:
                print("   No posted ledger entries found for this period.")
        else:
             print("   No expense accounts found.")

    except Exception as e:
        print(f"   Error analyzing expenses: {e}")
        import traceback
        traceback.print_exc()

    # 3b. ALTERNATIVE VOLUME (Bank Credits)
    print(f"\n3b. Checking Bank Credits (Alternative Volume)...")
    try:
        bank_credits = supabase.table('transacciones_bancarias').select('monto').eq('tipo', 'credito').gte('fecha', start_date).lte('fecha', end_date).execute()
        if bank_credits.data:
            total_credits = sum(Decimal(str(tx['monto'])) for tx in bank_credits.data)
            print(f"   Total Bank Credits: {format_currency(total_credits)}")
        else:
            print("   No bank credits found.")
    except Exception as e:
        print(f"   Error checking bank credits: {e}")

    # 4. BANK BALANCE (Latest)
    print(f"\n4. Checking Bank Balances (Latest Available)...")
    try:
        # Get list of bank accounts
        accounts_resp = supabase.table('cuentas_bancarias').select('banco, numero_cuenta, alias').execute()
        
        for acc in accounts_resp.data:
            banco = acc['banco']
            cuenta = acc['numero_cuenta']
            alias = acc.get('alias', f"{banco} - {cuenta}")
            
            # Try to find the latest transaction with a balance
            # Order by fecha desc, created_at desc
            latest_tx = supabase.table('transacciones_bancarias').select('fecha, saldo').eq('banco', banco).eq('cuenta_bancaria', cuenta).order('fecha', desc=True).limit(1).execute()
            
            if latest_tx.data:
                tx = latest_tx.data[0]
                saldo = tx.get('saldo')
                if saldo is not None:
                    print(f"   {alias}: {format_currency(Decimal(str(saldo)))} (as of {tx['fecha']})")
                else:
                    print(f"   {alias}: Balance not tracked in transactions (Latest tx: {tx['fecha']})")
            else:
                print(f"   {alias}: No transactions found.")
                
    except Exception as e:
        print(f"   Error checking bank balances: {e}")

if __name__ == "__main__":
    main()
