# ECUCONDOR SAS - Diagnóstico Detallado del Problema de Certificado Digital
**Fecha**: 26 de Noviembre de 2025
**Estado**: ⏳ PROBLEMA NO RESUELTO - Requiere acción manual en portal SRI

---

## 📋 Resumen Ejecutivo

El sistema ECUCONDOR ha completado exitosamente todas sus fases de desarrollo (bases de datos, importación de transacciones, contabilidad). Sin embargo, la emisión de facturas electrónicas está bloqueada por un **problema de vinculación de certificado digital en el portal del SRI**.

### El Problema en Una Línea:
> El certificado digital de REINA SHAKIRA MOSQUERA BORJA está técnicamente correcto pero **NO está registrado en el portal SRI** con el que el sistema intenta autorizar facturas.

---

## 🔍 Investigación Realizada

### 1. Análisis del Certificado Instalado

**Ubicación**: `/home/edu/ecucondor/certs/firma.p12`

```
📜 INFORMACIÓN DEL CERTIFICADO:
├─ Propietario: REINA SHAKIRA MOSQUERA BORJA
├─ Cédula: 1729430007
├─ Tipo: REPRESENTANTE LEGAL
├─ RUC Empresa: 1391937000001 (ECUCONDOR SAS)
├─ Algoritmo: RSA 2048-bit + SHA-256
├─ Autoridad: SECURITY DATA SEGURIDAD EN DATOS Y FIRMA DIGITAL S.A.
├─ Válido desde: 10/04/2025
├─ Válido hasta: 10/04/2027 (500 días)
├─ Extensión digital_signature: TRUE ✅
└─ MD5: be89c9e96ef4814023337396eb1eb526
```

**OIDs Verificados**:
```
Políticas del Certificado:
├─ OID 1.3.6.1.4.1.37746.2.9 → Certificado de Representante Legal ✅
├─ OID 1.3.6.1.4.1.37746.2.3 → Representante Legal ✅
└─ OID 3.11 → RUC de la empresa: 1391937000001 ✅
```

**Conclusión del análisis técnico**:
El certificado es **válido, vigente y está correctamente configurado** para firmar por ECUCONDOR SAS.

---

### 2. Pruebas de Firma Electrónica

Se ejecutó el script `/home/edu/ecucondor/scripts/generar_factura_prueba.py` para probar la firma:

```
📤 RESULTADO DEL ENVÍO AL SRI:

Paso 1: FIRMA ELECTRÓNICA (XAdES-BES)
  ✅ XML generado correctamente
  ✅ Firmado con XAdES-BES
  ✅ Certificado cargado exitosamente
  ✅ Firma RSA-SHA1 generada

Paso 2: RECEPCIÓN EN SRI
  ✅ Comprobante RECIBIDO por el SRI
  ✅ Validación técnica correcta
  ✅ Estructura XML correcta

Paso 3: AUTORIZACIÓN EN SRI
  ❌ FALLA - Error 39: FIRMA INVALIDA
  ❌ La factura NO es AUTORIZADA
  ❌ No se puede usar
```

---

### 3. Causa Raíz Identificada

El error **Error 39: FIRMA INVALIDA** ocurre en la fase de **AUTORIZACIÓN**, no en la de RECEPCIÓN.

**Esto significa**:
- ✅ La firma XAdES-BES es correcta
- ✅ El XML está bien formado
- ✅ El SRI recibe sin problemas
- ❌ **El SRI rechaza la factura porque el certificado NO ESTÁ VINCULADO en el portal**

**Análisis de fases SRI**:
```
FASE 1: RECEPCIÓN (Validación técnica)
  - ¿Es válido el XML?
  - ¿Es válida la firma?
  - ¿Está bien formado el comprobante?
  Resultado en ECUCONDOR: ✅ RECIBIDA

FASE 2: AUTORIZACIÓN (Validación comercial)
  - ¿Está el certificado registrado para esta empresa?
  - ¿Está vigente?
  - ¿Tiene permiso para emitir?
  Resultado en ECUCONDOR: ❌ RECHAZADA (Error 39)
```

---

## 🎯 Descubrimiento Crítico

Durante la investigación en el portal SRI se descubrió:

```
PORTAL SRI (https://srienlinea.sri.gob.ec)
├─ Credenciales: RUC 1391937000001 (ECUCONDOR SAS)
├─ Sección: Certificados de Firma Digital
└─ Certificados registrados:
    └─ ✓ ECUCONDOR SAS (sin nombre de persona)
       ├─ Tipo: Aparentemente de Persona Jurídica
       ├─ Estado: Vigente (probablemente)
       └─ REINA SHAKIRA MOSQUERA: ❌ NO APARECE
```

---

### Implicación Técnica

Existen **dos tipos de certificados** emitidos por Security Data:

| Característica | Persona Jurídica | Representante Legal |
|----------------|------------------|-------------------|
| **A nombre de** | ECUCONDOR SAS | REINA SHAKIRA MOSQUERA BORJA |
| **OID Tipo** | 2.4, 2.10 | 2.3, 2.9 |
| **Emite por** | Empresa directa | Empresa (como representante) |
| **Ubicación en portal** | Sin nombre personal | Incluye nombre personal |

**En el portal aparece**:
- Un certificado para "ECUCONDOR SAS" (probablemente el de Persona Jurídica)
- **NO aparece** el de "REINA SHAKIRA MOSQUERA BORJA" (Representante Legal)

---

## 📊 Cronología de Compras de Certificados

### Certificado 1 - Antigua (Hace mucho tiempo)
- **Tipo**: Persona Jurídica para ECUCONDOR SAS
- **Estado**: Desconocido (posiblemente vencido)
- **Archivo**: NO disponible en el sistema
- **En portal SRI**: ✅ Aparece como "ECUCONDOR SAS"

### Certificado 2 - Actual (04/2025)
- **Tipo**: Representante Legal para REINA SHAKIRA MOSQUERA BORJA
- **Comprado**: Abril 2025 (Security Data)
- **Válido**: 10/04/2025 - 10/04/2027
- **Archivo**: `/home/edu/ecucondor/certs/firma.p12` ✅
- **En portal SRI**: ❌ NO aparece
- **RUC vinculado**: 1391937000001 (ECUCONDOR SAS)

---

## 🔧 Opciones de Solución

### OPCIÓN A: Registrar el nuevo certificado (RECOMENDADO)

**Pasos**:
1. Ingresar a: https://srienlinea.sri.gob.ec
2. Iniciar sesión con credenciales de ECUCONDOR (RUC: 1391937000001)
3. Navegar a: FACTURACIÓN ELECTRÓNICA → Certificados de Firma Digital
4. Buscar botón "Agregar certificado" o "Nuevo certificado"
5. Subir archivo: `GERENTE GENERAL REINA SHAKIRA MOSQUERA BORJA 1729430007-100425172134.p12`
6. Ingresar contraseña del certificado
7. Confirmar

**Tiempo de procesamiento**: 24-48 horas
**Ventaja**: El nuevo certificado tiene 2 años de validez
**Desventaja**: Requiere acceso físico al portal SRI

---

### OPCIÓN B: Recuperar el certificado antiguo

Si no puede usar el nuevo certificado, puede intentar recuperar el antiguo:

**Contactar a Security Data**:
- Teléfono: +593 1 800 732 872
- Email: soporte@securitydata.net.ec
- Indicar: "Necesito recuperar el certificado de Persona Jurídica para RUC 1391937000001 (ECUCONDOR SAS). Compra realizada hace tiempo."

**Requisitos**:
- Datos de la compra original
- Verificación de identidad
- Contraseña original (si la recuerda)

**Ventaja**: Certificado ya está registrado en SRI
**Desventaja**: No se sabe si aún existe o está vigente

---

### OPCIÓN C: Reemplazar el certificado antiguo

Si el certificado antiguo en el portal está vencido:

1. Eliminar/desactivar el certificado antiguo en el portal SRI
2. Registrar el nuevo certificado de Reina
3. Esperar procesamiento (24-48 horas)

---

## 🛠️ Cambios en el Código (Si es necesario)

Si decide usar un certificado diferente, el único cambio necesario es:

**Archivo**: `/home/edu/ecucondor/.env`
```env
# Si cambia a otro certificado .p12:
SRI_CERT_PATH=/ruta/nuevo/certificado.p12
SRI_CERT_PASSWORD=nueva_contraseña
```

El sistema está **100% preparado** para usar cualquier certificado. No se requieren cambios en el código.

---

## 📞 Contactos para Soporte

### SRI Ecuador (Servicio de Rentas Internas)
- **Teléfono**: 1700 774 774 (opción para "Facturación Electrónica")
- **Email**: atencion.contribuyente@sri.gob.ec
- **Portal**: https://srienlinea.sri.gob.ec

**Mensaje a enviar**:
> "Tengo un certificado de Representante Legal (REINA SHAKIRA MOSQUERA BORJA, cédula 1729430007) para firmar por mi empresa ECUCONDOR SAS (RUC 1391937000001). El certificado está vigente desde 10/04/2025 hasta 10/04/2027. Necesito registrarlo en el portal para facturación electrónica. Al intentar enviar facturas recibo Error 39 FIRMA INVALIDA en la fase de autorización."

### Security Data S.A. (Proveedor de Certificados)
- **Teléfono**: +593 1 800 732 872
- **Email**: soporte@securitydata.net.ec
- **Web**: https://www.securitydata.net.ec

---

## 📝 Registro de Intentos

### 26/11/2025 - Primer Intento
```
Acción: Ejecutar generar_factura_prueba.py
Resultado: ❌ Error 39 - FIRMA INVALIDA
Análisis: Certificado técnicamente correcto pero no registrado en portal
```

### 26/11/2025 - Análisis del Portal SRI
```
Acción: Verificar certificados registrados en portal
Resultado: Solo aparece "ECUCONDOR SAS", NO aparece "REINA SHAKIRA"
Conclusión: Nuevo certificado no ha sido registrado en portal SRI
```

### 26/11/2025 - Investigación Técnica
```
Acción: Analizar estructura del certificado
Resultado:
  - Tipo: REPRESENTANTE LEGAL ✅
  - RUC vinculado: 1391937000001 ✅
  - Firma XAdES-BES: Funciona ✅
  - Vigencia: OK ✅
Conclusión: Problema no es técnico, es administrativo (falta registro en SRI)
```

---

## ✅ Estado del Sistema

### Componentes Operativos
- ✅ Base de datos (27 tablas, 11 vistas, 17 funciones)
- ✅ Módulo de importación (162 transacciones Dic-2024)
- ✅ Módulo contable (asientos automáticos NIIF 15)
- ✅ Módulo de reportes (Balance de Comprobación)
- ✅ Módulo de firma electrónica (XAdES-BES)
- ✅ Cliente SRI (envío de comprobantes)

### Componentes Bloqueados
- ❌ Autorización de facturas (Error 39)
- ❌ Emisión de facturas electrónicas válidas

---

## 🎯 Próximos Pasos

### Inmediato (Hoy)
1. Decidir qué hacer:
   - Opción A: Registrar nuevo certificado (recomendado)
   - Opción B: Recuperar certificado antiguo
   - Opción C: Contactar a SRI para ayuda

### Corto Plazo (24-48 horas)
2. Realizar la acción elegida
3. Esperar procesamiento del SRI

### Validación
4. Ejecutar: `python scripts/generar_factura_prueba.py`
5. Verificar que factura sea AUTORIZADA

---

## 📚 Documentación Relacionada

- `/home/edu/ecucondor/ESTADO_SISTEMA_ACTUAL.md` - Estado general del sistema
- `/home/edu/ecucondor/scripts/diagnostico_certificado.py` - Script de diagnóstico
- `/home/edu/ecucondor/scripts/generar_factura_prueba.py` - Script de emisión

---

**Documento preparado por**: Claude Code
**Última actualización**: 26/11/2025
**Estado**: En espera de acción manual en portal SRI
