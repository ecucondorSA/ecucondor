"""
ECUCONDOR - Configuración Centralizada
Sistema de Contabilidad Automatizada para SAS Unipersonal - Ecuador

Usa Pydantic Settings para validación y carga de variables de entorno.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Determinar la ruta del archivo .env
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    """Configuración principal de la aplicación."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== AMBIENTE =====
    environment: Literal["development", "staging", "production"] = "development"

    # ===== SUPABASE =====
    supabase_url: str = Field(..., description="URL del proyecto Supabase")
    supabase_key: str = Field(..., description="API Key pública de Supabase")
    supabase_service_key: str | None = Field(
        default=None, description="Service Role Key para operaciones admin"
    )
    database_url: str | None = Field(default=None, description="URL directa PostgreSQL")

    # ===== SRI - FACTURACIÓN ELECTRÓNICA =====
    sri_ambiente: Literal["1", "2"] = Field(
        default="1", description="1=Pruebas, 2=Producción"
    )
    sri_tipo_emision: Literal["1"] = Field(default="1", description="1=Normal")

    # Certificado
    sri_cert_path: str = Field(
        default="/app/certs/firma.p12", description="Ruta al certificado .p12"
    )
    sri_cert_password: str = Field(..., description="Contraseña del certificado")

    # Datos del emisor
    sri_ruc: str = Field(..., min_length=13, max_length=13, description="RUC del emisor")
    sri_razon_social: str = Field(..., max_length=300)
    sri_nombre_comercial: str | None = Field(default=None, max_length=300)
    sri_direccion_matriz: str = Field(...)
    sri_obligado_contabilidad: Literal["SI", "NO"] = "SI"
    sri_contribuyente_especial: str | None = None
    sri_regimen_microempresas: Literal["SI", "NO"] = "NO"
    sri_agente_retencion: str | None = None
    sri_rimpe: Literal["SI", "NO"] = "NO"

    # Establecimiento y punto de emisión
    sri_establecimiento: str = Field(default="001", min_length=3, max_length=3)
    sri_punto_emision: str = Field(default="001", min_length=3, max_length=3)

    # ===== IESS =====
    iess_codigo_relacion: str = Field(default="109", description="Código relación trabajo")
    iess_porcentaje_aporte: float = Field(default=17.6, description="Porcentaje aporte IESS")
    sbu_actual: float = Field(default=460.00, description="Salario Básico Unificado")

    # ===== UAFE =====
    uafe_umbral_resu: float = Field(default=10000.00, description="Umbral mensual USD")
    uafe_dias_plazo_resu: int = Field(default=15)
    uafe_dias_plazo_roii: int = Field(default=4)

    # ===== MODELO COMISIONISTA =====
    comision_porcentaje: float = Field(default=1.5, ge=0, le=100)
    pasivo_porcentaje: float = Field(default=98.5, ge=0, le=100)

    # ===== IVA =====
    iva_porcentaje: float = Field(default=15.0, description="Porcentaje IVA vigente")

    # ===== GMAIL MONITOR =====
    gmail_token_path: str = Field(
        default="/mnt/data/ECUCONDORULTIMATE/token.json",
        description="Ruta al token OAuth de Gmail",
    )
    gmail_poll_interval: int = Field(
        default=60, description="Segundos entre polls de Gmail"
    )

    # ===== NOTIFICACIONES (TELEGRAM) =====
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ===== EMAIL =====
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str | None = None

    # ===== AUTENTICACIÓN API =====
    auth_enabled: bool = Field(default=True, description="Habilitar autenticación API Key")
    api_key_secret: str = Field(
        default="", description="API Key para acceso a la API (mínimo 32 caracteres en producción)"
    )

    # ===== LOGGING =====
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    @field_validator("sri_ruc")
    @classmethod
    def validate_ruc(cls, v: str) -> str:
        """Validar formato de RUC ecuatoriano."""
        if not v.isdigit():
            raise ValueError("El RUC debe contener solo dígitos")
        if len(v) != 13:
            raise ValueError("El RUC debe tener exactamente 13 dígitos")
        # Los últimos 3 dígitos deben ser 001
        if not v.endswith("001"):
            raise ValueError("El RUC de persona jurídica debe terminar en 001")
        return v

    @field_validator("comision_porcentaje", "pasivo_porcentaje")
    @classmethod
    def validate_porcentaje_sum(cls, v: float) -> float:
        """Validar que los porcentajes estén en rango válido."""
        if v < 0 or v > 100:
            raise ValueError("El porcentaje debe estar entre 0 y 100")
        return v

    @property
    def is_production(self) -> bool:
        """Verificar si estamos en ambiente de producción."""
        return self.environment == "production"

    @property
    def sri_is_production(self) -> bool:
        """Verificar si el ambiente SRI es producción."""
        return self.sri_ambiente == "2"

    @property
    def sri_ws_recepcion(self) -> str:
        """URL del Web Service de recepción del SRI."""
        base = "cel" if self.sri_is_production else "celcer"
        return f"https://{base}.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline?wsdl"

    @property
    def sri_ws_autorizacion(self) -> str:
        """URL del Web Service de autorización del SRI."""
        base = "cel" if self.sri_is_production else "celcer"
        return f"https://{base}.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline?wsdl"


@lru_cache
def get_settings() -> Settings:
    """
    Obtener instancia cacheada de la configuración.

    El cache se limpia automáticamente al reiniciar la aplicación.
    Para forzar recarga en tests: get_settings.cache_clear()
    """
    return Settings()
