from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class ReportWindow(BaseModel):
    """The interval every report is measured over: Sydney calendar dates, `from` inclusive, `to` exclusive."""
    from_date: date
    to_date: date
    from_at: datetime
    to_at: datetime


class SalesRow(BaseModel):
    store_id: int
    store_name: str
    captured_amount: Decimal        # charges booked in the window, by their own event time
    refunded_amount: Decimal        # refunds booked in the window, by their own event time
    net_receipts: Decimal
    order_count: int                # orders placed in the window
    charged_orders: int             # orders with a charge booked in the window
    refund_count: int


class SalesReport(BaseModel):
    window: ReportWindow
    rows: list[SalesRow]
    totals: SalesRow


class LowStockRow(BaseModel):
    product_id: int
    sku: str
    name: str
    brand: str
    category: str
    current_price: Decimal
    quantity: int
    has_inventory_row: bool         # false means "never stocked here", which still counts as 0


class LowStockReport(BaseModel):
    store_id: int
    store_name: str
    threshold: int
    rows: list[LowStockRow]


class ReturnsRow(BaseModel):
    store_id: int
    store_name: str
    requested_count: int
    received_count: int
    refunded_count: int
    rejected_count: int
    refunded_amount: Decimal
    receiving_stores: str | None    # where the items were actually taken in, if anywhere


class ReturnsReport(BaseModel):
    window: ReportWindow
    rows: list[ReturnsRow]
    totals: ReturnsRow
