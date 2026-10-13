from app.config import normalize_redis_url_for_runtime


def test_windows_localhost_redis_url_uses_ipv4_for_docker_port_binding():
    assert normalize_redis_url_for_runtime(
        "redis://localhost:6379/0", platform_name="win32"
    ) == "redis://127.0.0.1:6379/0"


def test_windows_redis_url_preserves_credentials_database_and_query():
    assert normalize_redis_url_for_runtime(
        "redis://user:secret@localhost:6380/4?ssl_check_hostname=false",
        platform_name="win32",
    ) == "redis://user:secret@127.0.0.1:6380/4?ssl_check_hostname=false"


def test_non_windows_redis_hostname_is_unchanged_for_docker_network():
    assert normalize_redis_url_for_runtime(
        "redis://redis:6379/0", platform_name="linux"
    ) == "redis://redis:6379/0"


def test_non_windows_localhost_is_not_rewritten():
    assert normalize_redis_url_for_runtime(
        "redis://localhost:6379/0", platform_name="linux"
    ) == "redis://localhost:6379/0"


def test_api_rate_limiter_uses_the_same_windows_redis_normalization(monkeypatch):
    from api.middleware import _rate_limit_redis_url

    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/3")

    assert _rate_limit_redis_url(platform_name="win32") == "redis://127.0.0.1:6379/3"
    assert _rate_limit_redis_url(platform_name="linux") == "redis://localhost:6379/3"
