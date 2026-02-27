-- Verificación de Migraciones ECUCONDOR 005, 006, 007
-- Ejecutar después de aplicar las migraciones

-- 1️⃣ VERIFICAR TABLAS CREADAS (Debe ser 13)
SELECT COUNT(*) as total_tablas_creadas,
       STRING_AGG(tablename, ', ' ORDER BY tablename) as tablas
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN (
    'periodos_contables',
    'asientos_contables',
    'movimientos_contables',
    'saldos_cuentas',
    'comisiones_split',
    'administradores',
    'pagos_honorarios',
    'parametros_iess',
    'parametros_retencion_renta',
    'uafe_monitoreo_resu',
    'uafe_detecciones_roii',
    'uafe_reportes',
    'uafe_parametros'
  );

-- 2️⃣ VERIFICAR VISTAS CREADAS (Debe ser 7)
SELECT COUNT(*) as total_vistas,
       STRING_AGG(viewname, ', ' ORDER BY viewname) as vistas
FROM pg_views
WHERE schemaname = 'public'
  AND viewname IN (
    'v_libro_diario',
    'v_libro_mayor',
    'v_balance_comprobacion',
    'v_honorarios_pendientes',
    'v_resumen_honorarios_anual',
    'v_uafe_resu_pendientes',
    'v_uafe_roii_alto_riesgo'
  );

-- 3️⃣ VERIFICAR FUNCIONES CREADAS (Debe ser 7)
SELECT COUNT(*) as total_funciones,
       STRING_AGG(routine_name, ', ' ORDER BY routine_name) as funciones
FROM information_schema.routines
WHERE routine_schema = 'public'
  AND routine_name IN (
    'crear_periodo_si_no_existe',
    'contabilizar_asiento',
    'anular_asiento',
    'obtener_saldo_cuenta',
    'calcular_iess_109',
    'calcular_retencion_renta',
    'actualizar_monitoreo_resu'
  );

-- 4️⃣ VERIFICAR DATOS INICIALES - PARÁMETROS IESS
SELECT
    codigo_actividad,
    vigencia_desde,
    porcentaje_aporte_patronal,
    porcentaje_aporte_personal,
    salario_basico_unificado
FROM parametros_iess
WHERE codigo_actividad = '109' AND activo = true
LIMIT 1;

-- 5️⃣ VERIFICAR DATOS INICIALES - PARÁMETROS UAFE
SELECT
    umbral_resu_usd,
    umbral_efectivo_usd,
    umbral_monto_inusual,
    umbral_frecuencia_diaria,
    puntaje_riesgo_minimo
FROM uafe_parametros
WHERE activo = true
LIMIT 1;

-- 6️⃣ VERIFICAR FOREIGN KEYS
SELECT COUNT(*) as total_fk
FROM information_schema.table_constraints
WHERE constraint_type = 'FOREIGN KEY'
  AND table_schema = 'public'
  AND table_name IN (
    'movimientos_contables',
    'comisiones_split',
    'pagos_honorarios',
    'uafe_detecciones_roii'
  );

-- 7️⃣ VERIFICAR PERÍODO ACTUAL
SELECT
    COUNT(*) as periodos_creados,
    MAX(nombre) as periodo_mas_reciente,
    MIN(nombre) as periodo_mas_antiguo
FROM periodos_contables;

-- 8️⃣ TEST FUNCIONAL: Probar función de cálculo IESS
SELECT
    'Prueba IESS 109 - Honorarios $1000' as prueba,
    aporte_patronal,
    aporte_personal,
    (aporte_patronal + aporte_personal) as total_iess,
    CASE
        WHEN (aporte_patronal = 121.50 AND aporte_personal = 94.50) THEN '✅ Cálculo correcto'
        ELSE '❌ Error en cálculo'
    END as resultado
FROM calcular_iess_109(1000.00);

-- 9️⃣ TEST FUNCIONAL: Probar función de retención
SELECT
    'Prueba Retención 8% - Base $1000' as prueba,
    retencion,
    porcentaje,
    CASE
        WHEN (retencion = 80.00 AND porcentaje = 0.08) THEN '✅ Cálculo correcto'
        ELSE '❌ Error en cálculo'
    END as resultado
FROM calcular_retencion_renta(1000.00, 2025);

-- 🔟 RESUMEN FINAL
SELECT
    COUNT(DISTINCT table_name) as total_tablas_creadas,
    COUNT(DISTINCT routine_name) as total_funciones,
    'Migraciones 005, 006, 007 - COMPLETADAS' as estado
FROM (
    SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'
    UNION ALL
    SELECT routine_name FROM information_schema.routines WHERE routine_schema = 'public'
) as combined;
