"""
ECUCONDOR - Servicio de Auto-Facturación P2P
Genera facturas electrónicas automáticamente desde depósitos Produbanco.

Pipeline: Deposito → Comisión → XML → Firma → SRI → BD
"""

import hashlib
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from supabase import create_client, Client as SupabaseClient

from src.config.settings import Settings
from src.gmail.parser_produbanco import DepositoInfo
from src.notifications.telegram import enviar_alerta
from src.sri.access_key import generar_clave_acceso
from src.sri.client import SRIClient
from src.sri.models import FormaPago, TipoIdentificacion
from src.sri.signer_sri import XAdESSigner
from src.sri.xml_builder import crear_factura_xml

logger = logging.getLogger(__name__)

ECUADOR_TZ = timezone(timedelta(hours=-5))
PROCESSED_FILE = Path(__file__).parent.parent.parent / "data" / "emails_procesados.json"


class AutoInvoiceService:
    """Servicio que genera facturas electrónicas desde depósitos bancarios."""

    def __init__(self, settings: Settings, supabase: SupabaseClient):
        self.settings = settings
        self.db = supabase
        self.signer = XAdESSigner(
            cert_path=settings.sri_cert_path,
            cert_password=settings.sri_cert_password,
        )
        self.sri_client = SRIClient(ambiente=settings.sri_ambiente)

    def ya_procesado(self, gmail_message_id: str) -> bool:
        """Verifica si un email ya fue procesado (BD primario, JSON fallback)."""
        try:
            result = (
                self.db.table("gmail_facturas_procesadas")
                .select("id")
                .eq("gmail_message_id", gmail_message_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return True
        except Exception as e:
            logger.warning("Error consultando dedup BD: %s", str(e))

        # Fallback: archivo local
        processed = self._load_processed()
        return gmail_message_id in processed

    def _load_processed(self) -> dict:
        """Carga el registro de emails procesados."""
        PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
        if PROCESSED_FILE.exists():
            return json.loads(PROCESSED_FILE.read_text())
        return {}

    def _save_processed(self, gmail_message_id: str, data: dict) -> None:
        """Guarda un email como procesado."""
        processed = self._load_processed()
        processed[gmail_message_id] = {
            **data,
            "timestamp": datetime.now(ECUADOR_TZ).isoformat(),
        }
        PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROCESSED_FILE.write_text(json.dumps(processed, indent=2, default=str))

    def procesar_deposito(self, deposito: DepositoInfo) -> dict:
        """
        Procesa un depósito y genera la factura electrónica.

        Args:
            deposito: Datos del depósito extraídos del email

        Returns:
            Dict con datos de la factura generada

        Raises:
            Exception: Si falla algún paso del proceso
        """
        logger.info(
            "Procesando depósito: $%.2f de %s",
            deposito.monto, deposito.nombre_remitente,
        )

        # 1. Deduplicación atómica en BD
        try:
            self.db.table("gmail_facturas_procesadas").insert({
                "gmail_message_id": deposito.gmail_message_id,
                "deposito_monto": float(deposito.monto),
                "deposito_remitente": deposito.nombre_remitente,
                "deposito_fecha": deposito.fecha.isoformat(),
                "estado": "procesando",
            }).execute()
        except Exception as e:
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                logger.info("Email ya procesado (BD): %s", deposito.gmail_message_id)
                return {"estado": "duplicado", "message_id": deposito.gmail_message_id}
            # Si falla por otra razón, continuar con fallback JSON
            logger.warning("Error insertando dedup BD: %s", str(e))
            if self.ya_procesado(deposito.gmail_message_id):
                logger.info("Email ya procesado (JSON): %s", deposito.gmail_message_id)
                return {"estado": "duplicado", "message_id": deposito.gmail_message_id}

        # 2. Calcular comisión
        comision_porcentaje = Decimal(str(self.settings.comision_porcentaje))
        iva_porcentaje = Decimal(str(self.settings.iva_porcentaje))

        base_imponible = (deposito.monto * comision_porcentaje / Decimal("100")).quantize(Decimal("0.01"))
        valor_iva = (base_imponible * iva_porcentaje / Decimal("100")).quantize(Decimal("0.01"))
        total_factura = base_imponible + valor_iva

        logger.info(
            "Comisión: base=$%.2f, IVA=$%.2f, total=$%.2f",
            base_imponible, valor_iva, total_factura,
        )

        # 3. Resolver cliente
        tipo_id, identificacion, razon_social = self._resolver_cliente(deposito)

        # 4. Obtener siguiente secuencial
        secuencial = self._siguiente_secuencial()

        # 5. Fecha de emisión (hoy en Ecuador)
        fecha_emision = datetime.now(ECUADOR_TZ).date()

        # 6. Generar clave de acceso
        clave_acceso = generar_clave_acceso(
            fecha_emision=fecha_emision,
            tipo_comprobante="01",
            ruc=self.settings.sri_ruc,
            ambiente=self.settings.sri_ambiente,
            establecimiento=self.settings.sri_establecimiento,
            punto_emision=self.settings.sri_punto_emision,
            secuencial=secuencial,
            tipo_emision=self.settings.sri_tipo_emision,
        )

        logger.info(
            "Factura %s-%s-%09d | Clave: %s...",
            self.settings.sri_establecimiento,
            self.settings.sri_punto_emision,
            secuencial,
            clave_acceso[:20],
        )

        # 7. Generar XML
        xml_sin_firmar = crear_factura_xml(
            ruc=self.settings.sri_ruc,
            razon_social=self.settings.sri_razon_social,
            nombre_comercial=self.settings.sri_nombre_comercial,
            direccion_matriz=self.settings.sri_direccion_matriz,
            ambiente=self.settings.sri_ambiente,
            establecimiento=self.settings.sri_establecimiento,
            punto_emision=self.settings.sri_punto_emision,
            secuencial=secuencial,
            clave_acceso=clave_acceso,
            fecha_emision=fecha_emision,
            cliente_tipo_id=tipo_id,
            cliente_identificacion=identificacion,
            cliente_razon_social=razon_social,
            obligado_contabilidad=self.settings.sri_obligado_contabilidad,
            items=[
                {
                    "codigo": "SRV001",
                    "descripcion": f"Comision por intermediacion P2P - {deposito.nombre_remitente}",
                    "cantidad": 1,
                    "precio_unitario": float(base_imponible),
                    "aplica_iva": True,
                    "porcentaje_iva": float(iva_porcentaje),
                }
            ],
            forma_pago=FormaPago.SIN_SISTEMA_FINANCIERO,
            info_adicional={
                "Email": "ecucondor@gmail.com",
                "MontoTransferencia": f"${deposito.monto:.2f}",
                "Referencia": deposito.referencia or "N/A",
            },
        )

        # 8. Firmar
        xml_firmado = self.signer.sign(xml_sin_firmar)
        logger.info("XML firmado correctamente")

        # 9. Enviar al SRI
        resultado_recepcion = self.sri_client.enviar_comprobante(xml_firmado)

        if resultado_recepcion.estado != "RECIBIDA":
            error_msg = f"SRI rechazó comprobante: {resultado_recepcion.estado}"
            if resultado_recepcion.comprobantes:
                for comp in resultado_recepcion.comprobantes:
                    for msg in comp.get("mensajes", []):
                        error_msg += f" | {msg.get('identificador')}: {msg.get('mensaje')}"
            logger.error(error_msg)
            self._registrar_error(deposito, error_msg)
            raise Exception(error_msg)

        logger.info("Comprobante RECIBIDO por SRI")

        # 10. Consultar autorización (con espera)
        time.sleep(3)
        resultado_auth = self.sri_client.consultar_autorizacion(clave_acceso)

        numero_autorizacion = None
        fecha_autorizacion = None
        estado_final = "sent"

        if resultado_auth.autorizaciones and len(resultado_auth.autorizaciones) > 0:
            auth = resultado_auth.autorizaciones[0]
            if auth.estado == "AUTORIZADO":
                numero_autorizacion = auth.numero_autorizacion
                fecha_autorizacion = auth.fecha_autorizacion
                estado_final = "authorized"
                logger.info("Factura AUTORIZADA: %s", numero_autorizacion)
            else:
                estado_final = "error"
                error_msg = f"No autorizada: {auth.estado}"
                if auth.mensajes:
                    for msg in auth.mensajes:
                        error_msg += f" | {msg.identificador}: {msg.mensaje}"
                logger.warning(error_msg)

        # 11. Guardar en BD
        comprobante_data = {
            "tipo_comprobante": "01",
            "establecimiento": self.settings.sri_establecimiento,
            "punto_emision": self.settings.sri_punto_emision,
            "secuencial": f"{secuencial:09d}",
            "clave_acceso": clave_acceso,
            "fecha_emision": fecha_emision.isoformat(),
            "cliente_tipo_id": tipo_id.value if hasattr(tipo_id, "value") else tipo_id,
            "cliente_identificacion": identificacion,
            "cliente_razon_social": razon_social,
            "subtotal_sin_impuestos": float(base_imponible),
            "total_descuento": 0.0,
            "subtotal_15": float(base_imponible),
            "subtotal_0": 0.0,
            "iva": float(valor_iva),
            "importe_total": float(total_factura),
            "estado": estado_final,
            "xml_firmado": xml_firmado,
            "intentos_envio": 1,
            "ultimo_intento_at": datetime.now(ECUADOR_TZ).isoformat(),
        }

        if numero_autorizacion:
            comprobante_data["numero_autorizacion"] = numero_autorizacion
        if fecha_autorizacion:
            comprobante_data["fecha_autorizacion"] = (
                fecha_autorizacion.isoformat()
                if hasattr(fecha_autorizacion, "isoformat")
                else str(fecha_autorizacion)
            )

        comp_result = (
            self.db.table("comprobantes_electronicos")
            .insert(comprobante_data)
            .execute()
        )
        comprobante_id = comp_result.data[0]["id"] if comp_result.data else None

        # 12. Registrar transacción bancaria
        hash_unico = hashlib.sha256(
            f"{deposito.fecha}|{deposito.monto}|{deposito.referencia or ''}|{deposito.nombre_remitente}".encode()
        ).hexdigest()[:16]

        numero_factura = f"{self.settings.sri_establecimiento}-{self.settings.sri_punto_emision}-{secuencial:09d}"

        tx_data = {
            "hash_unico": hash_unico,
            "banco": "PRODUBANCO",
            "cuenta_bancaria": "2070809",
            "fecha": deposito.fecha.isoformat(),
            "tipo": "credito",
            "origen": "transferencia",
            "monto": float(deposito.monto),
            "descripcion_original": deposito.descripcion or f"Transferencia de {deposito.nombre_remitente}",
            "contraparte_nombre": deposito.nombre_remitente,
            "contraparte_identificacion": deposito.identificacion_remitente,
            "estado": "conciliada",
            "comprobante_id": comprobante_id,
        }

        try:
            self.db.table("transacciones_bancarias").insert(tx_data).execute()
        except Exception as e:
            # Si ya existe (duplicado hash), no es error crítico
            logger.warning("No se pudo insertar transacción bancaria: %s", str(e))

        # 13. Actualizar dedup BD con resultado
        try:
            self.db.table("gmail_facturas_procesadas").update({
                "comprobante_id": comprobante_id,
                "estado": "procesado" if estado_final == "authorized" else estado_final,
            }).eq("gmail_message_id", deposito.gmail_message_id).execute()
        except Exception as e:
            logger.warning("Error actualizando dedup BD: %s", str(e))

        # 14. Registrar email procesado (archivo local - log secundario)
        self._save_processed(deposito.gmail_message_id, {
            "monto": float(deposito.monto),
            "remitente": deposito.nombre_remitente,
            "fecha": deposito.fecha.isoformat(),
            "comprobante_id": comprobante_id,
            "estado": estado_final,
            "numero_factura": numero_factura,
        })

        logger.info(
            "Factura %s completada | Estado: %s | Total: $%.2f",
            numero_factura, estado_final, total_factura,
        )

        # 15. Notificar si no autorizada
        if estado_final != "authorized":
            self._notificar(f"ALERTA factura {numero_factura} estado: {estado_final}")

        return {
            "estado": estado_final,
            "numero": numero_factura,
            "clave_acceso": clave_acceso,
            "numero_autorizacion": numero_autorizacion,
            "total": float(total_factura),
            "comprobante_id": comprobante_id,
        }

    def _resolver_cliente(self, deposito: DepositoInfo) -> tuple:
        """
        Resuelve tipo_id, identificación y razón social del cliente.

        Returns:
            Tupla (TipoIdentificacion, identificacion_str, razon_social)
        """
        if deposito.identificacion_remitente:
            id_str = deposito.identificacion_remitente.strip()
            if len(id_str) == 10 and id_str.isdigit():
                return (
                    TipoIdentificacion.CEDULA,
                    id_str,
                    deposito.nombre_remitente,
                )
            elif len(id_str) == 13 and id_str.isdigit():
                return (
                    TipoIdentificacion.RUC,
                    id_str,
                    deposito.nombre_remitente,
                )

        # Sin identificación → consumidor final
        return (
            TipoIdentificacion.CONSUMIDOR_FINAL,
            "9999999999999",
            "CONSUMIDOR FINAL",
        )

    def _siguiente_secuencial(self) -> int:
        """Obtiene el siguiente secuencial para facturas (solo numéricos)."""
        result = (
            self.db.table("comprobantes_electronicos")
            .select("secuencial")
            .eq("tipo_comprobante", "01")
            .eq("establecimiento", self.settings.sri_establecimiento)
            .eq("punto_emision", self.settings.sri_punto_emision)
            .order("secuencial", desc=True)
            .limit(50)
            .execute()
        )

        if result.data:
            for row in result.data:
                sec = row["secuencial"]
                if sec.isdigit():
                    return int(sec) + 1
        return 1

    def reintentar_pendientes(self, max_intentos: int = 10) -> dict:
        """
        Reconsulta autorización para facturas en estado 'sent' o 'received'.

        Returns:
            Dict con contadores: reautorizadas, aun_pendientes, errores
        """
        result = (
            self.db.table("comprobantes_electronicos")
            .select("id, clave_acceso, secuencial, establecimiento, punto_emision, intentos_envio")
            .in_("estado", ["sent", "received"])
            .lt("intentos_envio", max_intentos)
            .execute()
        )

        pendientes = result.data or []
        if not pendientes:
            return {"reautorizadas": 0, "aun_pendientes": 0, "errores": 0}

        logger.info("Reintentando autorización para %d comprobantes", len(pendientes))

        reautorizadas = 0
        aun_pendientes = 0
        errores = 0

        for comp in pendientes:
            clave = comp["clave_acceso"]
            num = f"{comp['establecimiento']}-{comp['punto_emision']}-{comp['secuencial']}"
            intentos = (comp.get("intentos_envio") or 0) + 1

            try:
                resp = self.sri_client.consultar_autorizacion(clave)

                update_data = {
                    "intentos_envio": intentos,
                    "ultimo_intento_at": datetime.now(ECUADOR_TZ).isoformat(),
                }

                if resp.autorizaciones:
                    auth = resp.autorizaciones[0]
                    if auth.estado == "AUTORIZADO":
                        update_data["estado"] = "authorized"
                        update_data["numero_autorizacion"] = auth.numero_autorizacion
                        if auth.fecha_autorizacion:
                            update_data["fecha_autorizacion"] = (
                                auth.fecha_autorizacion.isoformat()
                                if hasattr(auth.fecha_autorizacion, "isoformat")
                                else str(auth.fecha_autorizacion)
                            )
                        logger.info("REAUTORIZADA %s (intento %d)", num, intentos)
                        self._notificar(f"REAUTORIZADA factura {num}")
                        reautorizadas += 1
                    elif auth.estado == "NO AUTORIZADO":
                        update_data["estado"] = "rejected"
                        msgs = "; ".join(
                            f"{m.identificador}: {m.mensaje}" for m in auth.mensajes
                        )
                        update_data["mensajes_sri"] = [{"error": msgs}]
                        logger.warning("RECHAZADA %s: %s", num, msgs)
                        self._notificar(f"RECHAZADA factura {num}: {msgs[:200]}")
                        errores += 1
                    else:
                        aun_pendientes += 1
                else:
                    aun_pendientes += 1

                self.db.table("comprobantes_electronicos").update(
                    update_data
                ).eq("id", comp["id"]).execute()

            except Exception as e:
                logger.warning("Error reintentando %s: %s", num, str(e))
                aun_pendientes += 1

            time.sleep(2)  # No saturar el WS del SRI

        return {
            "reautorizadas": reautorizadas,
            "aun_pendientes": aun_pendientes,
            "errores": errores,
        }

    def _notificar(self, mensaje: str) -> None:
        """Envía notificación por Telegram si está configurado."""
        enviar_alerta(
            mensaje,
            token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
        )

    def _registrar_error(self, deposito: DepositoInfo, error: str) -> None:
        """Registra un email procesado con error."""
        # Actualizar dedup BD
        try:
            self.db.table("gmail_facturas_procesadas").update({
                "estado": "error",
                "error_detalle": error[:500],
            }).eq("gmail_message_id", deposito.gmail_message_id).execute()
        except Exception as e:
            logger.warning("Error actualizando dedup BD: %s", str(e))

        # Log en archivo JSON
        try:
            self._save_processed(deposito.gmail_message_id, {
                "monto": float(deposito.monto),
                "remitente": deposito.nombre_remitente,
                "fecha": deposito.fecha.isoformat(),
                "estado": "error",
                "error": error[:500],
            })
        except Exception as e:
            logger.error("Error registrando fallo: %s", str(e))

        # Notificar
        self._notificar(f"ERROR factura para {deposito.nombre_remitente} (${deposito.monto}): {error[:200]}")
