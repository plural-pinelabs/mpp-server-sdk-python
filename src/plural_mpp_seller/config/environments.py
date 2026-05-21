"""Plural MPP environment base URLs."""


class MppEnvironment:
    SANDBOX: str = "https://pluraluat.v2.pinepg.in"
    PRODUCTION: str = "https://api.pluralpay.in"


DEFAULT_BASE_URL: str = MppEnvironment.PRODUCTION
DEFAULT_REALM: str = MppEnvironment.PRODUCTION
