"""
Certificate verification: fingerprint pinning for Lovense HTTPS.

Note: LOVENSE_HTTPS_FINGERPRINT may need updating if Lovense rotates their
certificate. The fingerprint can be overridden by passing a different value
to verify_cert_fingerprint().
"""

import hashlib
import socket
import ssl

__all__ = ["LOVENSE_HTTPS_FINGERPRINT", "verify_cert_fingerprint"]

# SHA-256 fingerprint of *.lovense.club (Lovense Remote HTTPS, port 30011)
LOVENSE_HTTPS_FINGERPRINT = (
    "EF:A7:4A:20:9B:B8:FC:C2:A8:1C:9F:51:51:DC:89:9A:E0:"
    "C5:CD:80:C4:93:D2:65:69:79:8D:CC:F5:A8:82:42"
)


def verify_cert_fingerprint(
    host: str,
    port: int,
    expected: str,
    timeout: float = 10.0,
) -> bool:
    """
    Verify server certificate SHA-256 fingerprint.

    Returns True if the peer certificate fingerprint matches expected.
    expected format: "EF:A7:4A:20:..." (colon-separated hex).
    """
    expected_norm = expected.replace(":", "").upper()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                der = ssock.getpeercert(binary_form=True)
    except (ssl.SSLError, OSError):
        return False
    digest = hashlib.sha256(der).hexdigest().upper()
    return digest == expected_norm
