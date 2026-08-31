from enum import Enum


class PaymentGateway(str, Enum):
    """Payment gateway enum retained for capture/receipt context."""

    PineLabsOnline = "PINE LABS ONLINE"


class PaymentMethod(str, Enum):
    """Payment methods supported by the current P3P service payload contract."""

    RESERVE_PAY = "RESERVE_PAY"
    OTM = "OTM"
    CARD = "CARD"
    CREDIT_EMI = "CREDIT_EMI"
    Crypto = "CRYPTO"


__all__ = ["PaymentGateway", "PaymentMethod"]
