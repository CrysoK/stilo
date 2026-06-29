import base64
import hashlib
from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet

class EncryptedCharField(models.CharField):
    """
    A CharField that automatically encrypts values when writing to the database
    and decrypts them when reading from the database, using cryptography.fernet.
    """
    description = "A CharField that encrypts its data on write and decrypts on read using Fernet."

    def get_fernet(self):
        key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
        if not key:
            # Fallback to SECRET_KEY for dev safety
            key = settings.SECRET_KEY
        
        # Derive a valid 32-byte key using SHA-256
        hashed = hashlib.sha256(key.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(hashed)
        return Fernet(fernet_key)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        if not isinstance(value, str):
            value = str(value)
        fernet = self.get_fernet()
        encrypted = fernet.encrypt(value.encode("utf-8"))
        return encrypted.decode("utf-8")

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        fernet = self.get_fernet()
        try:
            # Attempt decryption
            decrypted = fernet.decrypt(value.encode("utf-8"))
            return decrypted.decode("utf-8")
        except Exception:
            # If decryption fails (e.g. legacy plain text data, key change, etc.), return as is
            return value

    def to_python(self, value):
        if value is None or value == "":
            return value
        return super().to_python(value)
