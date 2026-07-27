from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CredentialEncryptionError(RuntimeError):
    """Raised when credential encryption cannot be performed safely."""


class CredentialCipher:
    def __init__(self, key: str | bytes | None):
        try:
            encoded_key = key.encode("ascii") if isinstance(key, str) else key
            if not encoded_key:
                raise ValueError
            self._fernet = Fernet(encoded_key)
        except (TypeError, ValueError) as exc:
            raise CredentialEncryptionError(
                "Credential encryption is not configured correctly"
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        if not isinstance(plaintext, str) or not plaintext:
            raise CredentialEncryptionError("Credential value is missing")
        try:
            return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        except (TypeError, ValueError, UnicodeError) as exc:
            raise CredentialEncryptionError("Credential encryption failed") from exc

    def decrypt(self, ciphertext: str | bytes) -> str:
        try:
            encoded = ciphertext.encode("ascii") if isinstance(ciphertext, str) else ciphertext
            if not encoded:
                raise InvalidToken
            return self._fernet.decrypt(encoded).decode("utf-8")
        except (InvalidToken, TypeError, ValueError, UnicodeError) as exc:
            raise CredentialEncryptionError("Credential decryption failed") from exc
