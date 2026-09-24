"""CA bundle = certifi + extra roots from certs/ (Russian Trusted Root/Sub CA).

Tochka and Alfa-Bank serve certificates issued by the Russian Ministry of Digital
Development CA, which is absent from certifi and most OS/browser stores.
An operator can still override the bundle with the REQUESTS_CA_BUNDLE env var.
"""
from __future__ import annotations

import atexit
import os
import tempfile
from functools import lru_cache
from pathlib import Path

import certifi

CERTS_DIR = Path(__file__).resolve().parent.parent / "certs"


def _bundle_text(certs_dir: Path) -> str:
    extra = [p.read_text(encoding="ascii") for p in sorted(certs_dir.glob("*.pem"))]
    return "\n".join([Path(certifi.where()).read_text(encoding="ascii"), *extra])


@lru_cache(maxsize=1)
def ca_bundle(certs_dir: Path = CERTS_DIR) -> str:
    """Path to a combined PEM bundle, created once per process."""
    if not any(certs_dir.glob("*.pem")):
        return certifi.where()
    with tempfile.NamedTemporaryFile(
        "w", encoding="ascii", prefix="bankmon-ca-", suffix=".pem", delete=False
    ) as fh:
        fh.write(_bundle_text(certs_dir))
    atexit.register(_remove_quietly, fh.name)
    return fh.name


def _remove_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
