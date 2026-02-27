"""
ECUCONDOR - Router Principal API v1
Agrupa todos los routers de la API.
"""

from fastapi import APIRouter

from src.api.v1 import clientes, compras, honorarios, invoices, ledger, sri, transactions

# Router principal de la API v1
router = APIRouter()

# Incluir routers de cada módulo
router.include_router(
    invoices.router,
    prefix="/invoices",
    tags=["Facturación"],
)

router.include_router(
    transactions.router,
    prefix="/transactions",
    tags=["Transacciones Bancarias"],
)

router.include_router(
    ledger.router,
    prefix="/ledger",
    tags=["Contabilidad"],
)

router.include_router(
    honorarios.router,
    prefix="/honorarios",
    tags=["Honorarios Administrador"],
)

router.include_router(
    compras.router,
    prefix="/compras",
    tags=["Módulo de Compras"],
)

router.include_router(
    sri.router,
    prefix="/sri",
    tags=["Servicios SRI"],
)

router.include_router(
    clientes.router,
    prefix="/clientes",
    tags=["Clientes"],
)

from src.api.v1 import uafe

# Integrar módulo UAFE
router.include_router(uafe.router, prefix="/uafe", tags=["Cumplimiento UAFE"])
