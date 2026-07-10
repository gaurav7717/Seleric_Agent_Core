"""Single-use, short-TTL confirmation tokens (HMAC-SHA256), same primitive as
seleric_systems dispatch_actions._generate_approval_token / _verify_hmac.
The commit cannot execute without a token minted from an actual preview.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def mint_token(secret: str, action_request_id: str, p_hash: str, expires_epoch: int) -> str:
    msg = f"{action_request_id}:{p_hash}:{expires_epoch}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).digest()
    raw = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    # Token embeds its own claims so commit() can re-verify without a lookup key.
    return f"{action_request_id}.{expires_epoch}.{raw}"


def parse_token(token: str) -> tuple[str, int, str] | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    action_request_id, expires_str, sig = parts
    try:
        return action_request_id, int(expires_str), sig
    except ValueError:
        return None


def verify_token(secret: str, token: str, p_hash: str) -> tuple[bool, str | None, int | None]:
    """Returns (signature_valid, action_request_id, expires_epoch). Constant-time compare."""
    parsed = parse_token(token)
    if parsed is None:
        return False, None, None
    action_request_id, expires_epoch, _ = parsed
    expected = mint_token(secret, action_request_id, p_hash, expires_epoch)
    return hmac.compare_digest(token, expected), action_request_id, expires_epoch


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
