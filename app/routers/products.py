from decimal import Decimal

from fastapi import APIRouter, HTTPException
from psycopg2.errors import ForeignKeyViolation

from app.db import DbCursor
from app.schema import ProductIn, ProductOut

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
def list_products(cur: DbCursor, min_price: Decimal = Decimal("0")):
    cur.execute(
        "SELECT id, name, price, stock, category_id FROM product WHERE price >= %s ORDER BY id",
        (min_price,),
    )
    return cur.fetchall()


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, cur: DbCursor):
    cur.execute(
        "SELECT id, name, price, stock, category_id FROM product WHERE id = %s",
        (product_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return row


@router.post("", response_model=ProductOut, status_code=201)
def create_product(product: ProductIn, cur: DbCursor):
    try:
        cur.execute(
            """
            INSERT INTO product (name, price, stock, category_id)
            VALUES (%s, %s, %s, %s)
            RETURNING id, name, price, stock, category_id
            """,
            (product.name, product.price, product.stock, product.category_id),
        )
    except ForeignKeyViolation:
        raise HTTPException(status_code=400, detail=f"Category {product.category_id} does not exist")
    return cur.fetchone()