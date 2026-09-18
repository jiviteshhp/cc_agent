"""Run the browser demo over HTTPS on one explicit private hotspot address."""
import argparse
import ipaddress
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CERT_DIR = ROOT / "state" / "phone_https"


def private_ipv4(value):
    address = ipaddress.IPv4Address(value)
    ranges = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if not any(address in ipaddress.ip_network(network) for network in ranges):
        raise ValueError("Use the laptop's private Wi-Fi IPv4 address, not the phone/gateway address.")
    return str(address)


def openssl(*args):
    subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True)


def prepare_certificates(host, directory=CERT_DIR):
    host = private_ipv4(host)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    ca_key, ca_cert = directory / "ca.key", directory / "Optha-Local-CA.crt"
    # Reuse the trust anchor across DHCP address changes. Never silently replace
    # a half-missing or expired CA: the phone would still trust its predecessor.
    if ca_key.exists() != ca_cert.exists():
        raise ValueError("Local CA is incomplete; restore its key/certificate pair before continuing.")
    if not ca_key.exists():
        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "365",
                "-subj", "/CN=Optha Local Demo CA", "-keyout", ca_key, "-out", ca_cert,
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    openssl("x509", "-checkend", "2592000", "-noout", "-in", ca_cert)
    ca_key.chmod(0o600)
    key, csr, cert = directory / "server.key", directory / "server.csr", directory / "server.crt"
    ext = directory / "server.ext"
    ext.write_text(f"subjectAltName=IP:{host}\nbasicConstraints=critical,CA:FALSE\n"
                   "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n")
    openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256",
            "-subj", "/CN=Optha Local Demo", "-keyout", key, "-out", csr)
    key.chmod(0o600)
    openssl("x509", "-req", "-in", csr, "-CA", ca_cert, "-CAkey", ca_key,
            "-CAcreateserial", "-days", "30", "-sha256", "-extfile", ext, "-out", cert)
    openssl("verify", "-CAfile", ca_cert, "-verify_ip", host, "-purpose", "sslserver", cert)
    return key, cert, ca_cert


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Laptop Wi-Fi IPv4 after connecting to the Android hotspot")
    parser.add_argument("--prepare-only", action="store_true", help="Create certificates without serving the app")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        host = private_ipv4(args.host)
        key, cert, ca_cert = prepare_certificates(host)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"HTTPS setup failed ({type(exc).__name__}). Check the address, OpenSSL, disk access and CA expiry.\n")
    print(f"Copy ONLY this public certificate to Android and install it as a CA certificate:\n{ca_cert}", flush=True)
    print(f"Then open https://{host}:8443 in Android Chrome. Keep the laptop and hotspot on.", flush=True)
    if args.prepare_only:
        return
    os.environ["LOCAL_DEMO_HOST"] = host
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    import uvicorn
    uvicorn.run("main:app", host=host, port=8443, ssl_keyfile=str(key),
                ssl_certfile=str(cert), proxy_headers=False, workers=1)


if __name__ == "__main__":
    main()
