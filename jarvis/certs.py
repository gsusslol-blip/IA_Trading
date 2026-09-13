"""Self-signed LAN certificates for optional HTTPS (Android / browser mic)."""

from __future__ import annotations

import datetime as dt
import ipaddress
import subprocess
from pathlib import Path

from jarvis.config import DATA_DIR
from jarvis.lan import lan_ipv4

CERT_DIR = DATA_DIR / "certs"
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"


def ensure_lan_certs() -> tuple[Path, Path]:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    if CERT_FILE.is_file() and KEY_FILE.is_file() and CERT_FILE.stat().st_size > 32:
        return CERT_FILE, KEY_FILE
    names = ["localhost", "ilaria.local", "ilaria"]
    ips = ["127.0.0.1", "::1", *lan_ipv4()]
    try:
        _write_cryptography(names, ips)
    except Exception:
        _write_openssl(names, ips)
    if not CERT_FILE.is_file() or not KEY_FILE.is_file():
        raise RuntimeError(
            "No pude generar cert.pem. Instalá OpenSSL o: pip install cryptography"
        )
    return CERT_FILE, KEY_FILE


def _write_cryptography(names: list[str], ips: list[str]) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.timezone.utc)
    san: list[x509.GeneralName] = [x509.DNSName(item) for item in names]
    for raw in ips:
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(raw)))
        except ValueError:
            continue
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Ilaria LAN")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Ilaria LAN")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )
    KEY_FILE.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _write_openssl(names: list[str], ips: list[str]) -> None:
    alt = ",".join([*(f"DNS:{n}" for n in names), *(f"IP:{ip}" for ip in ips)])
    completed = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "825",
            "-nodes",
            "-keyout",
            str(KEY_FILE),
            "-out",
            str(CERT_FILE),
            "-subj",
            "/CN=Ilaria LAN",
            "-addext",
            f"subjectAltName={alt}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "openssl failed")
