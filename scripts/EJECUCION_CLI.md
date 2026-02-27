# ECUCONDOR - Ejecución de Migraciones via CLI

## 🚀 Pasos para ejecutar las migraciones

### Paso 1: Obtener credenciales de Supabase

Ve a: https://app.supabase.com/project/qfgieogzspihbglvpqs/settings/api

Copia:
- **Database URL**: `postgresql://postgres:PASSWORD@db.qfgieogzspihbglvpqs.supabase.co:5432/postgres`
- **Reemplaza PASSWORD** con tu contraseña real

### Paso 2: Opción A - Usar supabase CLI (Recomendado)

```bash
# Instalar supabase CLI (si no lo tienes)
npm install -g @supabase/cli

# O con homebrew
brew install supabase/tap/supabase

# Ir al directorio del proyecto
cd /home/edu/ecucondor

# Hacer login en Supabase
supabase login

# Ejecutar todas las migraciones pendientes
supabase db push

# Esto ejecutará automáticamente:
# - 005_ledger_journal.sql
# - 006_honorarios.sql
# - 007_uafe_compliance.sql
```

### Paso 2: Opción B - Usar psql directo

```bash
# Exportar la contraseña
export PGPASSWORD="tu_contraseña_real"

# Ejecutar las 3 migraciones en orden
psql -h db.qfgieogzspihbglvpqs.supabase.co \
     -U postgres \
     -d postgres \
     -f supabase/migrations/005_ledger_journal.sql

psql -h db.qfgieogzspihbglvpqs.supabase.co \
     -U postgres \
     -d postgres \
     -f supabase/migrations/006_honorarios.sql

psql -h db.qfgieogzspihbglvpqs.supabase.co \
     -U postgres \
     -d postgres \
     -f supabase/migrations/007_uafe_compliance.sql
```

### Paso 3: Verificar que las migraciones se ejecutaron

```bash
# Usar el script de verificación
export PGPASSWORD="tu_contraseña_real"

psql -h db.qfgieogzspihbglvpqs.supabase.co \
     -U postgres \
     -d postgres \
     -f scripts/verify_migrations.sql
```

Debe retornar:
- ✅ 13 tablas creadas
- ✅ 7 vistas creadas
- ✅ 7 funciones creadas
- ✅ Parámetros IESS correctos
- ✅ Parámetros UAFE correctos

## 🎯 Resumen de lo que se ejecutará

### Migración 005: Ledger Contable
```sql
-- 5 Tablas nuevas
CREATE TABLE periodos_contables (...)
CREATE TABLE asientos_contables (...)
CREATE TABLE movimientos_contables (...)
CREATE TABLE saldos_cuentas (...)
CREATE TABLE comisiones_split (...)

-- 3 Vistas nuevas
CREATE VIEW v_libro_diario (...)
CREATE VIEW v_libro_mayor (...)
CREATE VIEW v_balance_comprobacion (...)

-- 4 Funciones nuevas
CREATE FUNCTION crear_periodo_si_no_existe(...)
CREATE FUNCTION contabilizar_asiento(...)
CREATE FUNCTION anular_asiento(...)
CREATE FUNCTION obtener_saldo_cuenta(...)
```

### Migración 006: Honorarios IESS
```sql
-- 4 Tablas nuevas
CREATE TABLE administradores (...)
CREATE TABLE pagos_honorarios (...)
CREATE TABLE parametros_iess (...)
CREATE TABLE parametros_retencion_renta (...)

-- 2 Vistas nuevas
CREATE VIEW v_honorarios_pendientes (...)
CREATE VIEW v_resumen_honorarios_anual (...)

-- 2 Funciones nuevas
CREATE FUNCTION calcular_iess_109(...)
CREATE FUNCTION calcular_retencion_renta(...)

-- Datos iniciales
INSERT INTO parametros_iess VALUES (109, 12.15%, 9.45%, SBU=460)
INSERT INTO parametros_retencion_renta VALUES (2025, 8%)
```

### Migración 007: UAFE Compliance
```sql
-- 4 Tablas nuevas
CREATE TABLE uafe_monitoreo_resu (...)
CREATE TABLE uafe_detecciones_roii (...)
CREATE TABLE uafe_reportes (...)
CREATE TABLE uafe_parametros (...)

-- 2 Vistas nuevas
CREATE VIEW v_uafe_resu_pendientes (...)
CREATE VIEW v_uafe_roii_alto_riesgo (...)

-- 1 Función nueva
CREATE FUNCTION actualizar_monitoreo_resu(...)

-- Datos iniciales
INSERT INTO uafe_parametros VALUES (
    umbral_resu=10000,
    umbral_efectivo=10000,
    monto_inusual=50000
)
```

## 📋 Checklist de Ejecución

- [ ] Obtener credenciales de Supabase
- [ ] Exportar PGPASSWORD o hacer supabase login
- [ ] Ejecutar migración 005
  - [ ] Sin errores
  - [ ] 5 tablas creadas
  - [ ] 3 vistas creadas
  - [ ] 4 funciones creadas
- [ ] Ejecutar migración 006
  - [ ] Sin errores
  - [ ] 4 tablas creadas
  - [ ] 2 vistas creadas
  - [ ] 2 funciones creadas
  - [ ] Datos iniciales insertados
- [ ] Ejecutar migración 007
  - [ ] Sin errores
  - [ ] 4 tablas creadas
  - [ ] 2 vistas creadas
  - [ ] 1 función creada
  - [ ] Datos iniciales insertados
- [ ] Ejecutar script de verificación
  - [ ] Retorna 13 tablas
  - [ ] Retorna 7 vistas
  - [ ] Retorna 7 funciones
  - [ ] Parámetros IESS correctos
  - [ ] Parámetros UAFE correctos

## 🔗 URLs útiles

- **Dashboard Supabase**: https://app.supabase.com/project/qfgieogzspihbglvpqs
- **SQL Editor**: https://app.supabase.com/project/qfgieogzspihbglvpqs/sql
- **Settings API**: https://app.supabase.com/project/qfgieogzspihbglvpqs/settings/api

## 📞 Soporte

Si tienes errores durante la ejecución:

1. Verifica que la contraseña sea correcta
2. Verifica que estés en la red correcta
3. Ejecuta con debug: `supabase db push --debug`
4. Revisa los logs: `supabase logs --filter "error"`

## ✅ Resultado esperado

Después de ejecutar las 3 migraciones, tu base de datos tendrá:

- ✅ Sistema contable funcional (partida doble)
- ✅ Cálculos IESS automáticos (12.15% / 9.45%)
- ✅ Retención en la fuente (8%)
- ✅ Monitoreo UAFE (RESU/ROII)
- ✅ Parámetros para cierre fiscal 2024

Listo para:
1. Cargar datos 2024
2. Generar asientos contables
3. Registrar honorarios
4. Generar reportes financieros
5. Validar cumplimiento normativo (SRI, IESS, UAFE, NIIF)
