"""Turning a validated request into a fingerprint, so a retry can be told from a changed request.

The fingerprint is a SHA-256 of the *validated* request in a canonical form: keys sorted, lists in a
defined order, money and quantities as exact strings. Two requests that mean the same thing fingerprint
the same; anything else fingerprints differently.
"""
import hashlib
import json
from decimal import Decimal


def fingerprint_request(normalised_payload: dict) -> str:
    canonical = json.dumps(normalised_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def money(value) -> str:
    """Money as a fixed two-decimal string, so 19.9 and 19.90 are the same request."""
    return str(Decimal(value).quantize(Decimal("0.01")))


def order_fingerprint(body) -> str:
    """The fingerprint of a checkout request: lines sorted by product, prices never included."""
    return fingerprint_request({
        "fulfilment_method": body.fulfilment_method,
        "fulfilling_store_id": body.fulfilling_store_id,
        "delivery_address_no": body.delivery_address_no,
        "expected_total": money(body.expected_total),
        "items": sorted(
            ({"product_id": item.product_id, "quantity": item.quantity} for item in body.items),
            key=lambda item: item["product_id"],
        ),
    })


def return_fingerprint(body) -> str:
    """The fingerprint of a return request: lines sorted by the order line they come from."""
    return fingerprint_request({
        "reason": body.reason.strip(),
        "lines": sorted(
            ({"line_no": line.line_no, "quantity": line.quantity} for line in body.lines),
            key=lambda line: line["line_no"],
        ),
    })
