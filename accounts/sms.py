import logging
from abc import ABC, abstractmethod

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class SmsDeliveryError(Exception):
    pass


class SmsBackend(ABC):
    @abstractmethod
    def send(self, phone_number: str, message: str) -> None:
        """Deliver the message or raise SmsDeliveryError."""


class ConsoleSmsBackend(SmsBackend):
    """Development only: writes the message to the log instead of sending it."""

    def send(self, phone_number: str, message: str) -> None:
        logger.warning("DEV SMS to %s: %s", phone_number, message)


class HttpSmsBackend(SmsBackend):
    """Generic JSON-over-HTTP provider, configured entirely from settings."""

    def __init__(self):
        self.url = settings.SMS_API_URL
        self.api_key = settings.SMS_API_KEY
        if not self.url or not self.api_key:
            raise ImproperlyConfigured("SMS_API_URL and SMS_API_KEY must be set.")
        self.sender = settings.SMS_SENDER
        self.timeout = settings.SMS_TIMEOUT

    def send(self, phone_number: str, message: str) -> None:
        payload = {
            settings.SMS_PHONE_FIELD: phone_number,
            settings.SMS_MESSAGE_FIELD: message,
        }
        if self.sender:
            payload[settings.SMS_SENDER_FIELD] = self.sender
        try:
            response = requests.post(
                self.url,
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            # The message body contains the OTP, so it is never logged here.
            logger.exception("SMS delivery failed (to=%s)", phone_number)
            raise SmsDeliveryError("SMS delivery failed.") from exc


def get_sms_backend() -> SmsBackend:
    return import_string(settings.SMS_BACKEND)()
