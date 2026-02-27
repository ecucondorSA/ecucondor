# Certificados de Firma Electrónica

Este directorio contiene los certificados de firma electrónica para el SRI.

## IMPORTANTE - SEGURIDAD

⚠️ **NUNCA** commitear archivos de certificados al repositorio.

Los archivos `.p12`, `.pfx`, `.pem`, `.key` y `.crt` están excluidos en `.gitignore`.

## Archivos requeridos

1. **firma.p12** - Certificado de firma electrónica del SRI
   - Formato: PKCS#12
   - Debe estar vigente
   - Configurar la ruta en `SRI_CERT_PATH`
   - Configurar la contraseña en `SRI_CERT_PASSWORD`

## Obtención del certificado

El certificado de firma electrónica se obtiene de:

1. **Banco Central del Ecuador (BCE)**
   - https://www.eci.bce.ec/
   - Requiere token físico o archivo

2. **Security Data**
   - https://www.securitydata.net.ec/
   - Certificado en archivo .p12

3. **Otros emisores autorizados por el SRI**

## Verificación del certificado

```bash
# Ver información del certificado
openssl pkcs12 -in firma.p12 -info -noout

# Exportar certificado público
openssl pkcs12 -in firma.p12 -clcerts -nokeys -out cert.pem

# Ver fecha de expiración
openssl x509 -in cert.pem -noout -dates
```

## Renovación

Los certificados tienen validez de 1-2 años. Configurar alertas para renovar antes del vencimiento.
