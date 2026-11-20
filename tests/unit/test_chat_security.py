from frontend.chat_security import (
    SlidingWindowRateLimiter,
    is_loopback_host,
    issue_session_cookie,
    verify_session_cookie,
)


def test_signed_session_cookie_round_trip_and_auth_flag():
    secret = b"session-secret"
    cookie = issue_session_cookie("session-id", True, secret, expires_at=2_000_000_000)

    assert verify_session_cookie(cookie, secret, now=1_999_990_000) == (
        "session-id",
        True,
    )


def test_session_cookie_rejects_expiry_tampering_and_wrong_secret():
    secret = b"session-secret"
    cookie = issue_session_cookie("session-id", True, secret, expires_at=2_000_000_000)
    parts = cookie.split(".")
    tampered = ".".join([parts[0], parts[1], "0", parts[3]])

    assert verify_session_cookie(cookie, secret, now=2_000_000_000) is None
    assert verify_session_cookie(tampered, secret, now=1_999_990_000) is None
    assert verify_session_cookie(cookie, b"wrong-secret", now=1_999_990_000) is None
    assert verify_session_cookie("not-a-cookie", secret, now=1_999_990_000) is None


def test_session_cookie_rejects_unreasonably_far_expiry():
    cookie = issue_session_cookie("session-id", True, b"secret", expires_at=2_000_000_000)

    assert verify_session_cookie(cookie, b"secret", now=1_900_000_000) is None


def test_loopback_detection():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("192.168.1.4")
    assert not is_loopback_host(None)


def test_sliding_window_rate_limit_blocks_after_limit():
    limiter = SlidingWindowRateLimiter()

    assert limiter.allow("client", limit=2, window_seconds=60)
    assert limiter.allow("client", limit=2, window_seconds=60)
    assert not limiter.allow("client", limit=2, window_seconds=60)
