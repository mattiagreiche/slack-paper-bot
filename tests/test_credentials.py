import base64
import importlib
import importlib.util

import pytest


KEY_A = base64.urlsafe_b64encode(b"a" * 32).decode()
KEY_B = base64.urlsafe_b64encode(b"b" * 32).decode()
SLACK_TOKEN = "xoxb-secret-slack-token"


def test_settings_loads_credential_encryption_key_from_environment(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", KEY_A)

    settings = Settings(_env_file=None)

    assert settings.credential_encryption_key == KEY_A


def _credential_contract():
    module_name = "app.services.credentials"
    assert importlib.util.find_spec(module_name) is not None, (
        "F-13 requires app.services.credentials"
    )
    module = importlib.import_module(module_name)
    assert hasattr(module, "CredentialCipher")
    assert hasattr(module, "CredentialEncryptionError")
    return module.CredentialCipher, module.CredentialEncryptionError


def test_credential_cipher_round_trips_without_plaintext():
    CredentialCipher, _ = _credential_contract()
    cipher = CredentialCipher(KEY_A)

    ciphertext = cipher.encrypt(SLACK_TOKEN)

    assert ciphertext != SLACK_TOKEN
    assert SLACK_TOKEN not in str(ciphertext)
    assert cipher.decrypt(ciphertext) == SLACK_TOKEN


def test_credential_cipher_rejects_missing_or_malformed_key():
    CredentialCipher, CredentialEncryptionError = _credential_contract()

    for invalid_key in (None, "", "not-a-valid-encryption-key"):
        with pytest.raises(CredentialEncryptionError):
            CredentialCipher(invalid_key)


def test_credential_cipher_fails_closed_with_wrong_key():
    CredentialCipher, CredentialEncryptionError = _credential_contract()
    ciphertext = CredentialCipher(KEY_A).encrypt(SLACK_TOKEN)

    with pytest.raises(CredentialEncryptionError) as raised:
        CredentialCipher(KEY_B).decrypt(ciphertext)

    assert SLACK_TOKEN not in str(raised.value)
    assert str(ciphertext) not in str(raised.value)


def test_credential_cipher_fails_closed_when_ciphertext_is_tampered():
    CredentialCipher, CredentialEncryptionError = _credential_contract()
    cipher = CredentialCipher(KEY_A)
    ciphertext = cipher.encrypt(SLACK_TOKEN)
    if isinstance(ciphertext, bytes):
        tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 1])
    else:
        replacement = "A" if ciphertext[-1] != "A" else "B"
        tampered = ciphertext[:-1] + replacement

    with pytest.raises(CredentialEncryptionError) as raised:
        cipher.decrypt(tampered)

    assert SLACK_TOKEN not in str(raised.value)
    assert str(ciphertext) not in str(raised.value)
