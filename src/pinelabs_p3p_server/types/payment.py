from enum import Enum


class PaymentGateway(str, Enum):
    """Payment gateway enum retained for capture/receipt context."""

    PineLabsOnline = "PINE LABS ONLINE"


class PaymentMethod(str, Enum):
    """Payment methods supported by the current P3P service payload contract."""

    UPI_RESERVE_PAY = "RESERVE_PAY"
    Crypto = "CRYPTO"


__all__ = ["PaymentGateway", "PaymentMethod"]
