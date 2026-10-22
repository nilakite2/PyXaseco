"""Same-host request/response authentication without transmitting the shared secret."""

import hashlib
import hmac
import json
import re
import time
from uuid import uuid4


TERMINAL = frozenset({'completed', 'failed', 'cancelled', 'accepted', 'saved-not-applied'})


def _digest(token, parts):
    message = json.dumps(parts, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    return hmac.new(token.encode('ascii'), message, 'sha256').hexdigest()


def request_proof(token, method, path, headers, body):
    return _digest(token, ['pyxaseco-request-v1', method, path,
        headers.get('X-PyXaseco-Instance', ''), headers.get('X-PyXaseco-Run', ''),
        headers.get('X-PyXaseco-Time', ''), headers.get('X-PyXaseco-Nonce', ''),
        headers.get('X-Request-ID', ''), hashlib.sha256(body).hexdigest()])


def sign_request(token, method, path, headers, body):
    headers = {**headers, 'X-PyXaseco-Time': str(int(time.time())), 'X-PyXaseco-Nonce': uuid4().hex}
    headers['X-PyXaseco-Signature'] = request_proof(token, method, path, headers, body)
    return headers


def response_proof(token, request_signature, status, body):
    return _digest(token, ['pyxaseco-response-v1', request_signature, status, hashlib.sha256(body).hexdigest()])


def matches(proof, expected):
    return isinstance(proof, str) and re.fullmatch(r'[0-9a-f]{64}', proof) is not None and hmac.compare_digest(proof, expected)


class RequestVerifier:
    def __init__(self, token):
        self.token = token
        self.nonces = {}

    def verify(self, method, path, headers, body):
        stamp, nonce = headers.get('X-PyXaseco-Time', ''), headers.get('X-PyXaseco-Nonce', '')
        if (not re.fullmatch(r'[0-9]{10,11}', stamp) or abs(time.time() - int(stamp)) > 30
                or not re.fullmatch(r'[0-9a-f]{32}', nonce)):
            return False
        if not matches(headers.get('X-PyXaseco-Signature'), request_proof(self.token, method, path, headers, body)):
            return False
        now = time.monotonic()
        self.nonces = {value: expiry for value, expiry in self.nonces.items() if expiry > now}
        if nonce in self.nonces or len(self.nonces) >= 2048:
            return False
        self.nonces[nonce] = now + 65
        return True
