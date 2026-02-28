"""
ECUCONDOR - Sistema de Reintentos con Exponential Backoff
Maneja los reintentos automáticos para las comunicaciones con el SRI.
"""

import asyncio
import random
from functools import wraps
from typing import Any, Callable, TypeVar

import structlog
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T")


# Excepciones que justifican reintento
class RetryableError(Exception):
    """Error que puede ser reintentado."""
    pass


class SRIConnectionError(RetryableError):
    """Error de conexión con el SRI."""
    pass


class SRITimeoutError(RetryableError):
    """Timeout en la comunicación con el SRI."""
    pass


class SRIServiceUnavailable(RetryableError):
    """Servicio del SRI no disponible."""
    pass


# Excepciones que NO deben reintentarse
class SRIValidationError(Exception):
    """Error de validación del comprobante (no reintentable)."""
    pass


class SRIAuthorizationError(Exception):
    """Error de autorización (no reintentable)."""
    pass


class RetryConfig:
    """Configuración para reintentos."""

    # Máximo de intentos
    MAX_ATTEMPTS: int = 5

    # Tiempo base de espera (segundos)
    BASE_WAIT: float = 1.0

    # Tiempo máximo de espera entre reintentos (segundos)
    MAX_WAIT: float = 60.0

    # Multiplicador exponencial
    MULTIPLIER: float = 2.0

    # Jitter máximo (porcentaje)
    JITTER: float = 0.1


def with_retry(
    max_attempts: int = RetryConfig.MAX_ATTEMPTS,
    base_wait: float = RetryConfig.BASE_WAIT,
    max_wait: float = RetryConfig.MAX_WAIT,
) -> Callable:
    """
    Decorador para funciones síncronas con reintento exponential backoff.

    Args:
        max_attempts: Número máximo de intentos
        base_wait: Tiempo base de espera en segundos
        max_wait: Tiempo máximo de espera entre reintentos

    Returns:
        Función decorada con lógica de reintento
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=base_wait, max=max_wait),
        retry=retry_if_exception_type(RetryableError),
        before_sleep=lambda retry_state: logger.warning(
            "Reintentando operación",
            attempt=retry_state.attempt_number,
            wait=retry_state.next_action.sleep if retry_state.next_action else 0,
        ),
        reraise=True,
    )


def with_retry_async(
    max_attempts: int = RetryConfig.MAX_ATTEMPTS,
    base_wait: float = RetryConfig.BASE_WAIT,
    max_wait: float = RetryConfig.MAX_WAIT,
) -> Callable:
    """
    Decorador para funciones asíncronas con reintento exponential backoff.

    Args:
        max_attempts: Número máximo de intentos
        base_wait: Tiempo base de espera en segundos
        max_wait: Tiempo máximo de espera entre reintentos

    Returns:
        Función decorada con lógica de reintento
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_random_exponential(multiplier=base_wait, max=max_wait),
        retry=retry_if_exception_type(RetryableError),
        before_sleep=lambda retry_state: logger.warning(
            "Reintentando operación async",
            attempt=retry_state.attempt_number,
            wait=retry_state.next_action.sleep if retry_state.next_action else 0,
        ),
        reraise=True,
    )


class ExponentialBackoff:
    """
    Implementación manual de exponential backoff para control más granular.

    Útil cuando necesitas más control sobre el proceso de reintento,
    como logging personalizado o lógica condicional entre intentos.
    """

    def __init__(
        self,
        max_attempts: int = RetryConfig.MAX_ATTEMPTS,
        base_wait: float = RetryConfig.BASE_WAIT,
        max_wait: float = RetryConfig.MAX_WAIT,
        jitter: float = RetryConfig.JITTER,
    ):
        """
        Inicializa el backoff.

        Args:
            max_attempts: Número máximo de intentos
            base_wait: Tiempo base de espera en segundos
            max_wait: Tiempo máximo de espera
            jitter: Factor de aleatoriedad (0-1)
        """
        self.max_attempts = max_attempts
        self.base_wait = base_wait
        self.max_wait = max_wait
        self.jitter = jitter
        self.attempt = 0

    def reset(self) -> None:
        """Reinicia el contador de intentos."""
        self.attempt = 0

    def get_wait_time(self) -> float:
        """
        Calcula el tiempo de espera para el intento actual.

        Returns:
            Tiempo de espera en segundos
        """
        wait = min(
            self.base_wait * (RetryConfig.MULTIPLIER ** self.attempt),
            self.max_wait
        )

        # Agregar jitter
        jitter_range = wait * self.jitter
        wait += random.uniform(-jitter_range, jitter_range)

        return max(0, wait)

    def should_retry(self) -> bool:
        """
        Verifica si se debe hacer otro intento.

        Returns:
            True si hay intentos restantes
        """
        return self.attempt < self.max_attempts

    def next_attempt(self) -> int:
        """
        Avanza al siguiente intento.

        Returns:
            Número del intento actual
        """
        self.attempt += 1
        return self.attempt

    async def wait(self) -> None:
        """Espera el tiempo correspondiente antes del siguiente intento."""
        wait_time = self.get_wait_time()
        logger.debug(
            "Esperando antes de reintentar",
            attempt=self.attempt,
            wait_seconds=f"{wait_time:.2f}",
        )
        await asyncio.sleep(wait_time)

    def wait_sync(self) -> None:
        """Versión síncrona de wait."""
        import time
        wait_time = self.get_wait_time()
        logger.debug(
            "Esperando antes de reintentar (sync)",
            attempt=self.attempt,
            wait_seconds=f"{wait_time:.2f}",
        )
        time.sleep(wait_time)


async def retry_operation(
    operation: Callable[[], T],
    max_attempts: int = RetryConfig.MAX_ATTEMPTS,
    base_wait: float = RetryConfig.BASE_WAIT,
    max_wait: float = RetryConfig.MAX_WAIT,
    retryable_exceptions: tuple = (RetryableError,),
) -> T:
    """
    Ejecuta una operación con reintentos.

    Args:
        operation: Función a ejecutar
        max_attempts: Número máximo de intentos
        base_wait: Tiempo base de espera
        max_wait: Tiempo máximo de espera
        retryable_exceptions: Tupla de excepciones que permiten reintento

    Returns:
        Resultado de la operación

    Raises:
        Exception: La última excepción si se agotan los intentos
    """
    backoff = ExponentialBackoff(
        max_attempts=max_attempts,
        base_wait=base_wait,
        max_wait=max_wait,
    )

    last_exception: Exception | None = None

    while backoff.should_retry():
        attempt = backoff.next_attempt()

        try:
            logger.debug("Ejecutando operación", attempt=attempt, max_attempts=max_attempts)

            # Ejecutar operación
            if asyncio.iscoroutinefunction(operation):
                result = await operation()
            else:
                result = operation()

            logger.debug("Operación exitosa", attempt=attempt)
            return result

        except retryable_exceptions as e:
            last_exception = e
            logger.warning(
                "Operación falló (reintentable)",
                attempt=attempt,
                max_attempts=max_attempts,
                error=str(e),
            )

            if backoff.should_retry():
                await backoff.wait()
            else:
                logger.error(
                    "Agotados los intentos de reintento",
                    total_attempts=attempt,
                    last_error=str(e),
                )

        except Exception as e:
            # Excepción no reintentable
            logger.error(
                "Operación falló (no reintentable)",
                attempt=attempt,
                error=str(e),
            )
            raise

    if last_exception:
        raise last_exception

    raise RuntimeError("No se pudo completar la operación")


def classify_sri_error(error_code: str, error_message: str) -> Exception:
    """
    Clasifica un error del SRI para determinar si es reintentable.

    Args:
        error_code: Código de error del SRI
        error_message: Mensaje de error

    Returns:
        Excepción apropiada según el tipo de error
    """
    # Errores de conexión/disponibilidad (reintentables)
    connection_errors = ["70", "71", "72", "73"]
    timeout_errors = ["80", "81"]

    # Errores de validación (no reintentables)
    validation_errors = ["35", "36", "37", "38", "39", "40", "41", "42", "43", "44", "45"]

    # Mensajes de diagnóstico para errores comunes
    diagnostics = {
        "39": (
            "FIRMA INVALIDA - Verificar: (1) certificado .p12 registrado en "
            "srienlinea.sri.gob.ec > Facturación Electrónica, "
            "(2) certificado vigente, (3) RUC del emisor coincide con el del certificado"
        ),
        "35": "CLAVE DE ACCESO EN PROCESAMIENTO - El comprobante ya fue recibido, consultar autorización",
        "43": "CLAVE DE ACCESO REGISTRADA - El comprobante ya fue autorizado previamente",
    }

    if error_code in connection_errors:
        return SRIConnectionError(f"Error de conexión SRI [{error_code}]: {error_message}")

    if error_code in timeout_errors:
        return SRITimeoutError(f"Timeout SRI [{error_code}]: {error_message}")

    if "no disponible" in error_message.lower() or "service unavailable" in error_message.lower():
        return SRIServiceUnavailable(f"Servicio no disponible [{error_code}]: {error_message}")

    if error_code in validation_errors:
        detail = diagnostics.get(error_code, error_message)
        return SRIValidationError(f"Error de validación [{error_code}]: {detail}")

    # Por defecto, tratar como error de validación (no reintentar)
    return SRIValidationError(f"Error SRI [{error_code}]: {error_message}")
