import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _multifernet(keys: tuple) -> MultiFernet:
    return MultiFernet([Fernet(k.encode()) for k in keys])


def _fernet() -> MultiFernet:
    return _multifernet(tuple(settings.FIELD_ENCRYPTION_KEYS))


class EncryptedTextField(models.TextField):
    """
    Text stored encrypted (Fernet / AES-128-CBC + HMAC) in the database, so a
    leaked database dump or backup does not expose survivors' details.
    Trade-off: encrypted columns cannot be searched or filtered in SQL.
    """

    description = "Text encrypted at rest"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return _fernet().encrypt(value.encode("utf-8")).decode("ascii")

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken:
            logger.error("Could not decrypt a value (wrong or rotated key?)")
            return ""
