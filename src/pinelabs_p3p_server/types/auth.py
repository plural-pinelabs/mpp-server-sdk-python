from dataclasses import dataclass


@dataclass
class AuthResponse:
    access_token: str
    token_type: str
    expires_in: int
    scope: str


@dataclass
class AuthState:
    access_token: str
    expires_at: float
    scope: str
