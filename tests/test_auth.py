"""Session tokens, roles and the login rate limiter (pure logic, no HTTP)."""
import pytest

from app.auth import SESSION_TTL, Auth, LoginLimiter

NOW = 1_800_000_000.0


def make(admin="adm-pass", team="team-pass", secret=b"k" * 32):
    return Auth({"admin": admin, "team": team}, secret)


def test_password_maps_to_role():
    auth = make()
    assert auth.check_password("adm-pass") == "admin"
    assert auth.check_password("team-pass") == "team"
    assert auth.check_password("nope") is None
    assert auth.check_password("") is None


def test_empty_password_disables_role():
    auth = make(team="")
    assert auth.check_password("") is None
    assert auth.issue("team", NOW) is None


def test_token_roundtrip_and_expiry():
    auth = make()
    token = auth.issue("admin", NOW)
    assert auth.verify(token, NOW + 60) == "admin"
    assert auth.verify(token, NOW + SESSION_TTL - 1) == "admin"
    assert auth.verify(token, NOW + SESSION_TTL + 1) is None


@pytest.mark.parametrize("mutate", [
    lambda t: t.replace("team", "admin", 1),
    lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),
    lambda t: "garbage",
    lambda t: "",
    lambda t: "admin.notanumber.sig",
])
def test_tampered_token_is_rejected(mutate):
    auth = make()
    assert auth.verify(mutate(auth.issue("team", NOW)), NOW) is None


def test_other_secret_rejects_token():
    token = make().issue("admin", NOW)
    assert make(secret=b"z" * 32).verify(token, NOW) is None


def test_password_change_invalidates_only_that_role():
    admin_token, team_token = make().issue("admin", NOW), make().issue("team", NOW)
    changed = make(admin="new-admin-pass")
    assert changed.verify(admin_token, NOW) is None
    assert changed.verify(team_token, NOW) == "team"


def test_limiter_blocks_after_max_failures_within_window():
    lim = LoginLimiter(max_failures=3, window=100)
    for i in range(3):
        assert not lim.blocked("1.2.3.4", NOW + i)
        lim.failure("1.2.3.4", NOW + i)
    assert lim.blocked("1.2.3.4", NOW + 5)
    assert not lim.blocked("5.6.7.8", NOW + 5)          # per IP
    assert not lim.blocked("1.2.3.4", NOW + 103)        # window slid past the failures


def test_limiter_reset_on_success():
    lim = LoginLimiter(max_failures=2, window=100)
    lim.failure("ip", NOW)
    lim.reset("ip")
    lim.failure("ip", NOW + 1)
    assert not lim.blocked("ip", NOW + 2)
