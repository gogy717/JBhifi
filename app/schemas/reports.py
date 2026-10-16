"""What the reports look like to their readers (R9, plan §6 #4–#6). Money and rates are decimals, sent as strings."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class LowStockRow(BaseModel):
    product_id: int
    sku: str
    name: str
    category: str
    quantity: int
    sold_30d: int                       # units sold here in the last 30 days, whatever the report's window
    days_of_cover: Decimal | None       # quantity ÷ the daily rate of those 30 days; None when nothing sold


class CategorySales(BaseModel):
    category_id: int
    category: str
    parent_category: str | None
    orders: int                         # an order with lines in two categories counts in both
    units: int
    revenue: Decimal


class SalesTotal(BaseModel):
    orders: int
    units: int
    revenue: Decimal


class CategoryReturnRate(BaseModel):
    category_id: int
    category: str
    units_sold: int
    units_returned: int                 # of those units, how many came back (returns not rejected)
    return_rate: Decimal | None         # units_returned ÷ units_sold, 4 places; None when nothing sold


class ProductReturnRate(BaseModel):
    product_id: int
    sku: str
    name: str
    units_sold: int
    units_returned: int
    return_rate: Decimal


class StoreReport(BaseModel):
    """One store's report, every section read from one snapshot."""
    store_id: int
    store_name: str
    days: int                           # the window: sales placed in the last `days` days
    generated_at: datetime              # the snapshot's moment; the window ends here
    low_stock: list[LowStockRow]
    sales_by_category: list[CategorySales]
    sales_total: SalesTotal
    return_rate_by_category: list[CategoryReturnRate]
    return_rate_by_product: list[ProductReturnRate]
