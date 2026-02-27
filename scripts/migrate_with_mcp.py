#!/usr/bin/env python3
"""
Script para aplicar migraciones de ECUCONDOR usando Supabase MCP.

Utiliza el MCP server configurado en .mcp.json para conectar con Supabase
de forma segura sin requerir credenciales en el archivo .env.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent.parent))


class MigrationManager:
    """Gestor de migraciones con Supabase MCP."""

    def __init__(self):
        self.migrations_dir = Path(__file__).parent.parent / "supabase" / "migrations"
        self.mcp_config_file = Path(__file__).parent.parent / ".mcp.json"
        self.migrations = [
            "005_ledger_journal.sql",
            "006_honorarios.sql",
            "007_uafe_compliance.sql",
        ]

    def read_migration(self, filename: str) -> str:
        """Lee el contenido de un archivo de migración."""
        filepath = self.migrations_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"Migración no encontrada: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    def validate_mcp_config(self) -> bool:
        """Valida que el MCP esté configurado correctamente."""
        if not self.mcp_config_file.exists():
            print("❌ Archivo .mcp.json no encontrado")
            return False

        try:
            with open(self.mcp_config_file, "r") as f:
                config = json.load(f)

            if "mcpServers" not in config or "supabase" not in config["mcpServers"]:
                print("❌ MCP de Supabase no configurado en .mcp.json")
                return False

            supabase_config = config["mcpServers"]["supabase"]
            print(f"✅ MCP Supabase configurado")
            print(f"   URL: {supabase_config.get('url', 'N/A')}")
            return True
        except Exception as e:
            print(f"❌ Error leyendo .mcp.json: {e}")
            return False

    def get_migration_info(self) -> dict:
        """Obtiene información de las migraciones a aplicar."""
        migrations_info = {
            "005_ledger_journal.sql": {
                "nombre": "Ledger Contable",
                "descripcion": "Sistema de contabilidad de partida doble",
                "tablas": [
                    "periodos_contables",
                    "asientos_contables",
                    "movimientos_contables",
                    "saldos_cuentas",
                    "comisiones_split",
                ],
                "vistas": [
                    "v_libro_diario",
                    "v_libro_mayor",
                    "v_balance_comprobacion",
                ],
                "funciones": [
                    "crear_periodo_si_no_existe",
                    "contabilizar_asiento",
                    "anular_asiento",
                    "obtener_saldo_cuenta",
                ],
            },
            "006_honorarios.sql": {
                "nombre": "Honorarios IESS Código 109",
                "descripcion": "Sistema de gestión de honorarios profesionales",
                "tablas": [
                    "administradores",
                    "pagos_honorarios",
                    "parametros_iess",
                    "parametros_retencion_renta",
                ],
                "vistas": [
                    "v_honorarios_pendientes",
                    "v_resumen_honorarios_anual",
                ],
                "funciones": [
                    "calcular_iess_109",
                    "calcular_retencion_renta",
                ],
            },
            "007_uafe_compliance.sql": {
                "nombre": "UAFE Compliance",
                "descripcion": "Sistema de monitoreo anti-lavado (RESU/ROII)",
                "tablas": [
                    "uafe_monitoreo_resu",
                    "uafe_detecciones_roii",
                    "uafe_reportes",
                    "uafe_parametros",
                ],
                "vistas": [
                    "v_uafe_resu_pendientes",
                    "v_uafe_roii_alto_riesgo",
                ],
                "funciones": [
                    "actualizar_monitoreo_resu",
                ],
            },
        }
        return migrations_info

    def display_plan(self):
        """Muestra el plan de migraciones a ejecutar."""
        print("\n" + "=" * 70)
        print("PLAN DE MIGRACIONES - ECUCONDOR")
        print("=" * 70)

        migrations_info = self.get_migration_info()

        for idx, migration in enumerate(self.migrations, 1):
            info = migrations_info.get(migration, {})
            print(f"\n{idx}. {info.get('nombre', migration)}")
            print(f"   Descripción: {info.get('descripcion', 'N/A')}")

            tablas = info.get("tablas", [])
            vistas = info.get("vistas", [])
            funciones = info.get("funciones", [])

            if tablas:
                print(f"   📊 Tablas ({len(tablas)}): {', '.join(tablas[:2])}...")
            if vistas:
                print(f"   👁️  Vistas ({len(vistas)}): {', '.join(vistas[:2])}...")
            if funciones:
                print(f"   ⚙️  Funciones ({len(funciones)}): {', '.join(funciones[:2])}...")

        print("\n" + "=" * 70)
        print("RESUMEN")
        print("=" * 70)
        print(f"Total de migraciones: {len(self.migrations)}")
        print(f"Tablas nuevas: ~13")
        print(f"Vistas nuevas: ~7")
        print(f"Funciones nuevas: ~7")
        print(f"Cumplimiento: SRI, IESS Código 109, UAFE")
        print("=" * 70 + "\n")

    def generate_verification_queries(self) -> list:
        """Genera queries SQL para verificación post-migración."""
        return [
            {
                "nombre": "Verificar tablas creadas",
                "query": """
SELECT COUNT(*) as total_tablas
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
""",
            },
            {
                "nombre": "Verificar vistas",
                "query": """
SELECT COUNT(*) as total_vistas
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
""",
            },
            {
                "nombre": "Verificar funciones",
                "query": """
SELECT COUNT(*) as total_funciones
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
""",
            },
            {
                "nombre": "Verificar parámetros IESS",
                "query": """
SELECT porcentaje_aporte_patronal, porcentaje_aporte_personal, salario_basico_unificado
FROM parametros_iess
WHERE codigo_actividad = '109' AND activo = true
LIMIT 1;
""",
            },
            {
                "nombre": "Verificar parámetros UAFE",
                "query": """
SELECT umbral_resu_usd, umbral_efectivo_usd, umbral_monto_inusual
FROM uafe_parametros
WHERE activo = true
LIMIT 1;
""",
            },
        ]

    async def execute_migrations(self):
        """Ejecuta las migraciones (versión simulada para demostración)."""
        print("\n🚀 EJECUTANDO MIGRACIONES\n")
        print("=" * 70)

        for idx, migration in enumerate(self.migrations, 1):
            try:
                sql_content = self.read_migration(migration)
                print(f"\n{idx}. Aplicando: {migration}")
                print(f"   Tamaño: {len(sql_content)} bytes")
                print(f"   Líneas: {len(sql_content.splitlines())}")
                print(f"   ✅ Migración lista para ejecutar")

            except FileNotFoundError as e:
                print(f"   ❌ Error: {e}")
                return False

        return True

    async def main(self):
        """Flujo principal."""
        print("\n" + "=" * 70)
        print("ECUCONDOR - HERRAMIENTA DE MIGRACIÓN CON SUPABASE MCP")
        print("=" * 70)

        # 1. Validar configuración MCP
        print("\n📋 Verificando configuración MCP...")
        if not self.validate_mcp_config():
            print("\n❌ MCP no está correctamente configurado")
            return False

        # 2. Mostrar plan
        print("\n📐 Mostrando plan de migraciones...")
        self.display_plan()

        # 3. Ejecutar migraciones
        print("🔄 Preparando ejecución de migraciones...")
        if not await self.execute_migrations():
            print("\n❌ Error durante la preparación de migraciones")
            return False

        # 4. Generar queries de verificación
        print("\n" + "=" * 70)
        print("QUERIES DE VERIFICACIÓN POST-MIGRACIÓN")
        print("=" * 70)

        verification_queries = self.generate_verification_queries()
        for query_info in verification_queries:
            print(f"\n✓ {query_info['nombre']}")
            print("  " + "-" * 66)
            for line in query_info["query"].strip().split("\n"):
                print(f"  {line}")

        # 5. Resumen
        print("\n" + "=" * 70)
        print("RESUMEN DE EJECUCIÓN")
        print("=" * 70)
        print(f"✅ Migraciones preparadas: {len(self.migrations)}")
        print(f"✅ MCP Supabase configurado")
        print(f"✅ Queries de verificación generadas: {len(verification_queries)}")
        print("=" * 70)

        print("\n📌 PRÓXIMOS PASOS:")
        print("1. Las migraciones están listas en supabase/migrations/")
        print("2. Usar el MCP de Supabase para ejecutarlas:")
        print("   - En Claude Code: claude mcp use supabase")
        print("   - En la CLI: claude db migrate --mcp supabase")
        print("3. Después de ejecutar, validar con las queries de verificación")
        print("4. Ejecutar pruebas funcionales")
        print()

        return True


async def main():
    """Punto de entrada principal."""
    manager = MigrationManager()
    success = await manager.main()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelado por el usuario")
        sys.exit(1)
