"""The CA bundle must trust both public roots and the Russian Trusted Root CA."""
from pathlib import Path

import certifi

from bank_api_parser.parsers.tbank_parser import TBankParser
from bank_api_parser.tls import CERTS_DIR, ca_bundle


def test_repo_ships_russian_root_and_sub_ca():
    names = {p.name for p in CERTS_DIR.glob("*.pem")}
    assert {"russian_trusted_root_ca.pem", "russian_trusted_sub_ca.pem"} <= names


def test_bundle_contains_certifi_and_russian_roots():
    text = Path(ca_bundle()).read_text(encoding="ascii")
    assert Path(certifi.where()).read_text(encoding="ascii") in text
    for pem in CERTS_DIR.glob("*.pem"):
        assert pem.read_text(encoding="ascii").strip() in text


def test_bundle_falls_back_to_certifi_without_extra_certs(tmp_path):
    assert ca_bundle(tmp_path) == certifi.where()


def test_parser_sessions_use_the_bundle():
    assert TBankParser().session.verify == ca_bundle()
