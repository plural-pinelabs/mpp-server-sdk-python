from __future__ import annotations

from typing import Any, Dict, Optional

from ..types.config import Amount
from ..types.orders import (
    Order,
    OrderAcquirerData,
    OrderAddress,
    OrderCardData,
    OrderCustomer,
    OrderPayment,
    OrderPaymentOption,
    OrderPurchaseDetails,
    Refund,
)
from ..types.payment import PaymentMethod


def parse_order(data: Dict[str, Any]) -> Order:
    purchase_data = _mapping(data.get("purchase_details"))
    customer_data = _mapping(purchase_data.get("customer"))
    return Order(
        order_id=_text(data.get("order_id")),
        merchant_order_reference=_text(data.get("merchant_order_reference")),
        type=_text(data.get("type")),
        status=_text(data.get("status")),
        merchant_id=_text(data.get("merchant_id")),
        order_amount=_amount(data.get("order_amount")),
        pre_auth=bool(data.get("pre_auth", False)),
        purchase_details=OrderPurchaseDetails(
            customer=_customer(customer_data) if customer_data else None,
            merchant_metadata=_mapping(purchase_data.get("merchant_metadata")),
        ) if purchase_data else None,
        payments=[_payment(item) for item in data.get("payments", []) if isinstance(item, dict)],
        created_at=_optional_text(data.get("created_at")),
        updated_at=_optional_text(data.get("updated_at")),
        raw=data,
    )


def parse_refund(data: Dict[str, Any]) -> Refund:
    order = parse_order(data)
    return Refund(**order.__dict__, parent_order_id=_text(data.get("parent_order_id")))


def _customer(data: Dict[str, Any]) -> OrderCustomer:
    billing = _mapping(data.get("billing_address"))
    shipping = _mapping(data.get("shipping_address"))
    return OrderCustomer(
        email_id=_optional_text(data.get("email_id")),
        first_name=_optional_text(data.get("first_name")),
        last_name=_optional_text(data.get("last_name")),
        customer_id=_optional_text(data.get("customer_id")),
        mobile_number=_optional_text(data.get("mobile_number")),
        billing_address=OrderAddress(**_address_fields(billing)) if billing else None,
        shipping_address=OrderAddress(**_address_fields(shipping)) if shipping else None,
    )


def _payment(data: Dict[str, Any]) -> OrderPayment:
    option = _mapping(data.get("payment_option"))
    card = _mapping(option.get("card_data"))
    acquirer = _mapping(data.get("acquirer_data"))
    method = _text(data.get("payment_method"))
    try:
        payment_method: Any = PaymentMethod(method)
    except ValueError:
        payment_method = method
    return OrderPayment(
        id=_text(data.get("id")),
        status=_text(data.get("status")),
        payment_amount=_amount(data.get("payment_amount")),
        payment_method=payment_method,
        payment_option=OrderPaymentOption(
            card_data=OrderCardData(**{key: _optional_text(card.get(key)) for key in (
                "card_type", "network_name", "issuer_name", "card_category", "country_code", "token_txn_type"
            )}) if card else None,
        ) if option else None,
        acquirer_data=OrderAcquirerData(
            approval_code=_optional_text(acquirer.get("approval_code")),
            acquirer_reference=_optional_text(acquirer.get("acquirer_reference")),
            rrn=_optional_text(acquirer.get("rrn")),
            is_aggregator=bool(acquirer.get("is_aggregator", False)),
        ) if acquirer else None,
        created_at=_optional_text(data.get("created_at")),
        updated_at=_optional_text(data.get("updated_at")),
    )


def _amount(value: Any) -> Amount:
    data = _mapping(value)
    try:
        amount_value = int(data.get("value", 0) or 0)
    except (TypeError, ValueError):
        amount_value = 0
    return Amount(value=amount_value, currency=_text(data.get("currency") or "INR"))


def _address_fields(data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    return {key: _optional_text(data.get(key)) for key in (
        "address1", "address2", "address3", "pincode", "city", "state", "country"
    )}


def _mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _optional_text(value: Any) -> Optional[str]:
    return None if value is None else str(value)
