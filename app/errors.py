"""One error shape for every failure: {"error": {"code", "message", "detail"}}.

When the database rejects a request, the code is the violated constraint's name (brNN_… for business
rules), so the frontend — and in Phase 2 the support agent — knows exactly which rule was broken.
The API only checks the *shape* of a request (types, lengths); the rules themselves live in the
database, so each rule is enforced in exactly one place.
"""
from typing import Any

import psycopg2
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

# Readable messages for declarative constraints (CHECK, UNIQUE, FK). Trigger rules already raise a
# readable message of their own, so they don't need an entry.
CONSTRAINT_MESSAGES = {
    "br02_money_nonneg": "Prices can't be negative.",
    "br03_inventory_qty_nonneg": "Not enough stock: a store's quantity can't go below zero.",
    "br18_adjustment_staff_at_store": "Only staff who work at this store can adjust its stock.",
    "br18_adjustment_delta_matches_reason":
        "The reason doesn't fit the change: received stock is added, damaged stock is removed.",
    "product_sku_unique": "Another product already has this SKU.",
    "product_sku_format": "A SKU is upper-case letters and digits in groups joined by hyphens, e.g. SONY-WH1000XM5-B.",
    "product_brand_fk": "That brand doesn't exist.",
    "product_category_fk": "That category doesn't exist.",
    "product_spec_pk": "Each spec name can only appear once per product.",
    "promotion_period_valid": "A promotion must end after it starts.",
    "promotion_product_fk": "That product doesn't exist.",
    "au_state_valid": "That isn't an Australian state or territory: use NSW, VIC, QLD, WA, SA, TAS, ACT or NT.",
    "au_postcode_format": "A postcode is four digits, e.g. 2000.",
    # Checkout (T1): the order header and its lines.
    "customer_order_store_fk": "That store doesn't exist.",
    "br06_order_address_matches_method":
        "A delivery order needs one of your addresses, and a Click & Collect order has none.",
    "br17_order_address_is_customers": "That address isn't one of yours.",
    "br07_order_line_qty_positive": "Each quantity must be at least 1.",
    "br07_order_line_product_once": "Each product can appear only once in an order: change its quantity instead.",
    # Return requests: their lines.
    "return_line_order_line_fk": "That line isn't on this order.",
    "return_line_pk": "Each line can appear only once in a return: change its quantity instead.",
    "return_line_qty_positive": "Each quantity must be at least 1.",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: Any = None):
        super().__init__(message)
        self.status, self.code, self.message, self.detail = status, code, message, detail


class NotFound(ApiError):
    def __init__(self, what: str, key: Any):
        super().__init__(404, "not_found", f"{what} {key} not found")


class ErrorInfo(BaseModel):
    code: str
    message: str
    detail: Any = None


class ErrorResponse(BaseModel):
    error: ErrorInfo


# Documents the error shape in OpenAPI, so the generated TypeScript client knows it too.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Not signed in, or the sign-in token is not valid"},
    403: {"model": ErrorResponse, "description": "Signed in, but not allowed to do this"},
    404: {"model": ErrorResponse, "description": "Not found"},
    409: {"model": ErrorResponse, "description": "Rejected by a database rule; code = constraint name"},
    422: {"model": ErrorResponse, "description": "Malformed request"},
    503: {"model": ErrorResponse, "description": "The sign-in provider could not be reached"},
}


def error_response(status: int, code: str, message: str, detail: Any = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "detail": jsonable_encoder(detail)}}
    return JSONResponse(status_code=status, content=body)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.detail)

    # Class 23 (integrity constraint violation): CHECK, UNIQUE, FK, NOT NULL — and our trigger rules,
    # which raise check_violation with CONSTRAINT = 'brNN_…'.
    @app.exception_handler(psycopg2.IntegrityError)
    async def integrity_error(request: Request, exc: psycopg2.IntegrityError):
        code = exc.diag.constraint_name or exc.pgcode
        message = CONSTRAINT_MESSAGES.get(code, exc.diag.message_primary)
        return error_response(409, code, message, exc.diag.message_detail)

    # Class 22 (data exception), e.g. a number too large for its column.
    @app.exception_handler(psycopg2.DataError)
    async def data_error(request: Request, exc: psycopg2.DataError):
        return error_response(422, "invalid_value", exc.diag.message_primary)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(422, "validation_error", "The request is not valid.", exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return error_response(exc.status_code, f"http_{exc.status_code}", str(exc.detail))
