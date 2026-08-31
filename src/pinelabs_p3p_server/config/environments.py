"""Pine Labs Online P3P environment base URLs."""


class P3PEnvironment:
    SANDBOX: str = "https://pluraluat.v2.pinepg.in"
    PRODUCTION: str = "https://api.pluralpay.in"


P3PEnvironmentDefaults = {
    P3PEnvironment.SANDBOX: {
        "requestTimeoutMs": 60_000,
        "maxRetries": 2,
        "initialRetryDelayMs": 300,
    },
    P3PEnvironment.PRODUCTION: {
        "requestTimeoutMs": 45_000,
        "maxRetries": 2,
        "initialRetryDelayMs": 200,
    },
}


DEFAULT_BASE_URL: str = P3PEnvironment.PRODUCTION
DEFAULT_REALM: str = P3PEnvironment.PRODUCTION


def is_p3p_environment(value: object) -> bool:
    if value in (P3PEnvironment.SANDBOX, P3PEnvironment.PRODUCTION):
        return True
    if isinstance(value, str):
        if value.startswith("https://"):
            return True
        if value.startswith("http://"):
            return _is_localhost_url(value)
    return False


def _is_localhost_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        hostname = urlparse(url).hostname or ""
        return (
            hostname in ("localhost", "127.0.0.1", "::1", "host.docker.internal")
            or "." not in hostname  # single-label: Docker service names, local dev
        )
    except Exception:
        return False


def resolve_p3p_base_url(env: str) -> str:
    if not is_p3p_environment(env):
        raise ValueError("env must be P3PEnvironment.SANDBOX, P3PEnvironment.PRODUCTION, or an HTTP URL")
    return env


def with_p3p_environment_defaults(config):
    defaults = P3PEnvironmentDefaults.get(config.env, P3PEnvironmentDefaults[P3PEnvironment.SANDBOX])
    config.requestTimeoutMs = config.requestTimeoutMs or defaults["requestTimeoutMs"]
    config.maxRetries = defaults["maxRetries"] if config.maxRetries is None else config.maxRetries
    config.initialRetryDelayMs = config.initialRetryDelayMs or defaults["initialRetryDelayMs"]
    return config
