import base64
import json
import os
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_pem_public_key

_PUBLIC_KEY_PATH = os.path.join(os.path.dirname(__file__), "public_key.pem")
_VALID_PLANS = {"trial", "monthly", "annual", "lifetime"}
_PREFIX = "STAFFORYX-LIC-"

_public_key = None


def _load_public_key():
    global _public_key
    if _public_key is None:
        with open(_PUBLIC_KEY_PATH, "rb") as f:
            _public_key = load_pem_public_key(f.read())
    return _public_key


def _b64url_decode(s: str) -> bytes:
    padding = (4 - len(s) % 4) % 4
    return base64.urlsafe_b64decode(s + "=" * padding)


def verify_signed_license(license_key: str):
    """
    Verify an Ed25519-signed license key.
    Returns (True, payload_dict) on success, (False, error_str) on failure.
    """
    if not isinstance(license_key, str):
        return False, "License key must be a string."

    license_key = license_key.strip()

    if not license_key.startswith(_PREFIX):
        return False, "Invalid license key format."

    rest = license_key[len(_PREFIX):]
    if "." not in rest:
        return False, "Malformed license key — missing signature separator."

    encoded_payload, encoded_sig = rest.rsplit(".", 1)

    try:
        sig_bytes = _b64url_decode(encoded_sig)
    except Exception:
        return False, "Could not decode license signature."

    try:
        pub = _load_public_key()
    except FileNotFoundError:
        return False, "License verification is not configured (public key missing)."
    except Exception as exc:
        return False, f"Could not load public key: {exc}"

    try:
        pub.verify(sig_bytes, encoded_payload.encode("utf-8"))
    except InvalidSignature:
        return False, "License signature is invalid — key may be tampered or forged."
    except Exception as exc:
        return False, f"Signature verification error: {exc}"

    try:
        raw = _b64url_decode(encoded_payload)
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return False, "Could not decode license payload."

    # Validate required fields
    if payload.get("product") != "STAFFORYX_HR":
        return False, "License is not valid for this product."

    if payload.get("plan") not in _VALID_PLANS:
        return False, f"Unknown plan '{payload.get('plan')}' in license."

    for date_field in ("valid_from", "valid_until"):
        val = payload.get(date_field)
        if val:
            try:
                datetime.strptime(val, "%Y-%m-%d")
            except ValueError:
                return False, f"Invalid date format for '{date_field}'."

    max_emp = payload.get("max_employees")
    if not isinstance(max_emp, int) or max_emp < 1:
        return False, "Invalid max_employees value in license."

    return True, payload
