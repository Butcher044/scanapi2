"""Round-robin proxy rotation with cooldown and direct fallback (no network)."""
import pytest
import requests
from requests.adapters import HTTPAdapter

from bank_api_parser import proxy as px

P1, P2, P3 = "http://u:p@10.0.0.1:8000", "socks5://u:secret@10.0.0.2:1080", "http://10.0.0.3:3128"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_round_robin_starts_at_the_next_proxy_each_time():
    rot = px.ProxyRotator([P1, P2, P3], max_attempts=3)
    assert rot.candidates() == [P1, P2, P3]
    assert rot.candidates() == [P2, P3, P1]
    assert rot.candidates() == [P3, P1, P2]


def test_max_attempts_limits_candidates():
    rot = px.ProxyRotator([P1, P2, P3], max_attempts=2)
    assert rot.candidates() == [P1, P2]


def test_failed_proxy_cools_down_then_returns():
    clock = Clock()
    rot = px.ProxyRotator([P1, P2], cooldown=60, clock=clock)
    rot.report_failure(P1)
    assert P1 not in rot.candidates()
    clock.t = 61
    assert P1 in rot.candidates()


def test_empty_rotator_gives_no_candidates():
    assert px.ProxyRotator([]).candidates() == []


@pytest.fixture
def fake_send(monkeypatch):
    calls = []

    def send(self, request, **kwargs):
        proxy = (kwargs.get("proxies") or {}).get("https")
        calls.append(proxy)
        if proxy in fake_send.dead:
            raise requests.exceptions.ProxyError(f"Cannot connect to proxy {proxy}")
        if proxy in fake_send.hung:
            raise requests.exceptions.ReadTimeout("read timed out")
        resp = requests.Response()
        resp.status_code = 200
        resp._content = (proxy or "direct").encode()
        resp.url = request.url
        return resp

    fake_send.dead = set()
    fake_send.hung = set()
    fake_send.calls = calls
    monkeypatch.setattr(HTTPAdapter, "send", send)
    return fake_send


def _session(rotator):
    s = requests.Session()
    s.trust_env = False
    s.mount("https://", px.RotatingProxyAdapter(rotator))
    return s


def test_requests_rotate_across_proxies(fake_send):
    s = _session(px.ProxyRotator([P1, P2]))
    assert [s.get("https://bank.example/").text for _ in range(3)] == [P1, P2, P1]


def test_dead_proxy_is_skipped_and_next_one_used(fake_send):
    fake_send.dead = {P1}
    rot = px.ProxyRotator([P1, P2])
    s = _session(rot)
    assert s.get("https://bank.example/").text == P2
    assert s.get("https://bank.example/").text == P2      # P1 is cooling down
    assert fake_send.calls == [P1, P2, P2]


def test_all_proxies_dead_falls_back_to_direct(fake_send):
    fake_send.dead = {P1, P2}
    s = _session(px.ProxyRotator([P1, P2]))
    assert s.get("https://bank.example/").text == "direct"


def test_no_active_rotator_means_plain_adapter():
    px.set_active(None)
    adapter = px.make_adapter(max_retries=0)
    assert type(adapter) is HTTPAdapter
    px.set_active(px.ProxyRotator([P1]))
    try:
        assert isinstance(px.make_adapter(max_retries=0), px.RotatingProxyAdapter)
    finally:
        px.set_active(None)


@pytest.mark.parametrize("url,masked", [
    (P1, "http://u:***@10.0.0.1:8000"),
    (P2, "socks5://u:***@10.0.0.2:1080"),
    (P3, P3),
    ("socks5://onlyuser@h:1", "socks5://onlyuser@h:1"),
])
def test_mask_hides_password(url, masked):
    assert px.mask(url) == masked


def test_proxy_that_hangs_mid_response_is_skipped(fake_send):
    fake_send.hung = {P1}
    s = _session(px.ProxyRotator([P1, P2]))
    assert s.get("https://bank.example/").text == P2
    assert s.get("https://bank.example/").text == P2      # P1 is cooling down
