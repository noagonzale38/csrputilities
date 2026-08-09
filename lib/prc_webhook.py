"""Ed25519 signature verification for PRC (ER:LC) event webhooks.

The game signs every webhook request over `timestamp + raw_body` using the
public key published at https://apidocs.erlc.gg/event-webhooks.
"""

import base64
import logging

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_der_public_key

log = logging.getLogger(__name__)

# Ed25519 public key (base64, SubjectPublicKeyInfo / SPKI) from the PRC docs.
PRC_WEBHOOK_PUBLIC_KEY_B64 = "MCowBQYDK2VwAyEAjSICb9pp0kHizGQtdG8ySWsDChfGqi+gyFCttigBNOA="

_public_key = load_der_public_key(base64.b64decode(PRC_WEBHOOK_PUBLIC_KEY_B64))


def verify_prc_signature(timestamp: str, signature_hex: str, raw_body: bytes) -> bool:
    """Verify an Ed25519 webhook signature over timestamp + raw body bytes."""
    if not timestamp or not signature_hex:
        return False
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    try:
        _public_key.verify(signature, timestamp.encode("utf-8") + raw_body)
        return True
    except InvalidSignature:
        return False
    except Exception:
        log.exception("Unexpected error verifying PRC webhook signature")
        return False
