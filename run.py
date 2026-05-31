"""Secure Messenger — HTTPS Server

Usage:
    python run.py              # HTTPS (auto-generates cert if missing)
    python run.py --no-ssl     # HTTP only (for dev behind proxy)
"""
import sys
from pathlib import Path

import uvicorn

HOST = "0.0.0.0"
PORT = 8111
SSL_DIR = Path(__file__).parent
CERT = SSL_DIR / "cert.pem"
KEY = SSL_DIR / "key.pem"


def ensure_cert():
    """Generate self-signed certificate if missing."""
    if CERT.exists() and KEY.exists():
        return True

    print("🔑 Generating self-signed SSL certificate...")
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
        from cryptography.x509.oid import NameOID
        from datetime import datetime, timedelta, timezone
        import ipaddress, socket

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        hostname = socket.gethostname()

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "RU"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ])

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName(hostname),
                    x509.DNSName("localhost"),
                    x509.DNSName("127.0.0.1"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256(), backend=default_backend())
        )

        with open(CERT, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(KEY, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        print(f"✅ Certificate generated: {CERT.name}, {KEY.name}")
        return True
    except ImportError:
        print("⚠️  cryptography not installed. Run: pip install cryptography")
        return False
    except Exception as e:
        print(f"⚠️  Failed to generate cert: {e}")
        return False


if __name__ == "__main__":
    use_ssl = "--no-ssl" not in sys.argv and ensure_cert()

    if use_ssl:
        print(f"🔒 HTTPS on https://{HOST}:{PORT}")
        uvicorn.run(
            "backend.app.main:socket_app",
            host=HOST,
            port=PORT,
            reload=True,
            ssl_certfile=str(CERT),
            ssl_keyfile=str(KEY),
        )
    else:
        print(f"🔓 HTTP on http://{HOST}:{PORT}")
        uvicorn.run(
            "backend.app.main:socket_app",
            host=HOST,
            port=PORT,
            reload=True,
        )
