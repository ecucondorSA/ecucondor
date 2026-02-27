# Guía del ATS (Anexo Transaccional Simplificado) - Ecuador

## ¿Qué es el ATS?

El **Anexo Transaccional Simplificado (ATS)** es una declaración informativa mensual que los contribuyentes deben presentar al SRI (Servicio de Rentas Internas) de Ecuador. Contiene el resumen de todas las transacciones comerciales del período.

## Módulos del ATS

El ATS tiene varios módulos independientes:

| Módulo | Descripción | ¿Cuándo se usa? |
|--------|-------------|-----------------|
| **Compras** | Facturas recibidas de proveedores | Siempre (si hay compras) |
| **Ventas** | Facturas emitidas a clientes | Solo comprobantes físicos |
| **Retenciones** | Retenciones emitidas | Siempre (si hay retenciones) |
| **Anulados** | Comprobantes anulados | Solo si hay anulaciones |

## ¿Por qué "Carga en Cero"?

Tu ATS muestra **"carga en cero"** porque:

1. **No tiene módulo de compras** - ECUCONDOR no registra compras actualmente
2. **No tiene módulo de ventas** - Las facturas electrónicas NO van en el ATS

## Facturas Electrónicas vs ATS

### Las facturas electrónicas YA están reportadas al SRI

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUJO DE FACTURA ELECTRÓNICA                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ECUCONDOR  ──────────>  SRI  ──────────>  Cliente            │
│   (Emisor)      Envío       (Autoriza)       (Recibe)          │
│                 en tiempo                                       │
│                 real                                            │
│                                                                 │
│   ✅ SRI YA TIENE LA INFORMACIÓN DE CADA FACTURA               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Cuando emites una **factura electrónica**:
1. Se envía al SRI en tiempo real
2. El SRI la autoriza y guarda
3. El SRI ya conoce todos los detalles de la venta

**Por lo tanto: NO necesitas reportarla de nuevo en el ATS.**

### El módulo de Ventas del ATS es para comprobantes FÍSICOS

```
┌─────────────────────────────────────────────────────────────────┐
│              MÓDULO VENTAS DEL ATS - SOLO PARA:                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ❌ Facturas electrónicas (código 18)    - NO incluir         │
│   ✅ Facturas físicas pre-impresas (01)   - SÍ incluir         │
│   ✅ Notas de venta físicas (02)          - SÍ incluir         │
│   ✅ Liquidaciones físicas (03)           - SÍ incluir         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## ¿Qué debe ir en cada módulo?

### Módulo COMPRAS (lo que falta en ECUCONDOR)

Aquí van TODAS las facturas de compra recibidas:
- Facturas de proveedores
- Gastos operativos
- Compras de inventario
- Servicios recibidos

```xml
<compras>
  <detalleCompras>
    <codSustento>01</codSustento>
    <tpIdProv>04</tpIdProv>
    <idProv>1790123456001</idProv>
    <tipoComprobante>01</tipoComprobante>
    <!-- ... más campos ... -->
  </detalleCompras>
</compras>
```

### Módulo VENTAS (solo físicos)

Solo si emites comprobantes físicos (no electrónicos):

```xml
<ventas>
  <detalleVentas>
    <tpIdCliente>04</tpIdCliente>
    <idCliente>1791234567001</idCliente>
    <tipoComprobante>01</tipoComprobante>
    <!-- ... más campos ... -->
  </detalleVentas>
</ventas>
```

### Módulo RETENCIONES

Retenciones que has emitido a tus proveedores:

```xml
<retenciones>
  <detalleRetenciones>
    <!-- Datos de retención -->
  </detalleRetenciones>
</retenciones>
```

## Resumen para ECUCONDOR

| Transacción | ¿Va en ATS? | Razón |
|-------------|-------------|-------|
| Facturas electrónicas emitidas | ❌ NO | Ya están en el SRI |
| Notas de crédito electrónicas | ❌ NO | Ya están en el SRI |
| Compras (facturas recibidas) | ✅ SÍ | SRI necesita saber qué compraste |
| Retenciones emitidas | ✅ SÍ | Deben declararse |
| Comprobantes anulados | ✅ SÍ | Deben declararse |

## ¿Por qué el ATS actual solo tiene cabecera?

```xml
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<iva>
  <TipoIDInformante>R</TipoIDInformante>
  <IdInformante>1391937000001</IdInformante>
  <razonSocial>ECUCONDOR SAS</razonSocial>
  <Anio>2025</Anio>
  <Mes>09</Mes>
  <totalVentas>0.00</totalVentas>
  <codigoOperativo>IVA</codigoOperativo>
</iva>
```

Este ATS es válido porque:
1. ✅ ECUCONDOR solo emite facturas electrónicas (no van en ATS)
2. ✅ No hay compras registradas en el sistema
3. ✅ No hay retenciones emitidas
4. ✅ No hay comprobantes anulados

## Próximos Pasos para ECUCONDOR

Para tener un ATS completo, ECUCONDOR necesita:

1. **Módulo de Compras**: Registrar facturas de proveedores
2. **Módulo de Retenciones**: Si emite retenciones a proveedores
3. **Integración contable**: Conectar con sistema de gastos

## Referencias

- [Ficha Técnica ATS - SRI](https://www.sri.gob.ec/anexo-transaccional-simplificado-ats)
- [Catálogo de Códigos - SRI](https://www.sri.gob.ec/facturacion-electronica)
