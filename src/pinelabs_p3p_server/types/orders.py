from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from .config import Amount
from .payment import PaymentMethod


@dataclass
class OrderAddress:
    address1: Optional[str] = None
    address2: Optional[str] = None
    address3: Optional[str] = None
    pincode: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None


@dataclass
class OrderCustomer:
    email_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    customer_id: Optional[str] = None
    mobile_number: Optional[str] = None
    billing_address: Optional[OrderAddress] = None
    shipping_address: Optional[OrderAddress] = None


@dataclass
class OrderPurchaseDetails:
    customer: Optional[OrderCustomer] = None
    merchant_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderCardData:
    card_type: Optional[str] = None
    network_name: Optional[str] = None
    issuer_name: Optional[str] = None
    card_category: Optional[str] = None
    country_code: Optional[str] = None
    token_txn_type: Optional[str] = None


@dataclass
class OrderPaymentOption:
    card_data: Optional[OrderCardData] = None


@dataclass
class OrderAcquirerData:
    approval_code: Optional[str] = None
    acquirer_reference: Optional[str] = None
    rrn: Optional[str] = None
    is_aggregator: bool = False


@dataclass
class OrderPayment:
    id: str
    status: str
    payment_amount: Amount
    payment_method: Union[PaymentMethod, str]
    payment_option: Optional[OrderPaymentOption] = None
    acquirer_data: Optional[OrderAcquirerData] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Order:
    """Typed GetOrder response; raw retains future upstream fields."""

    order_id: str
    merchant_order_reference: str
    type: str
    status: str
    merchant_id: str
    order_amount: Amount
    pre_auth: bool
    purchase_details: Optional[OrderPurchaseDetails] = None
    payments: List[OrderPayment] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CreateRefundOptions:
    merchantOrderReference: str
    """Merchant-generated unique refund reference."""

    orderAmount: Amount
    """Refund amount in the smallest currency unit, e.g. paise for INR."""

    merchantMetadata: Optional[Dict[str, Any]] = None


@dataclass
class Refund(Order):
    parent_order_id: str = ""
