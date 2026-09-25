import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )

def create_product(name, price):
    conn = get_connection()
    try:
        with conn:                                    # commits on exit, rolls back on exception
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO product (name, price) VALUES (%s, %s) RETURNING id, name, price",
                    (name, price),                     # ← tuple, even for one param
                )
                return cur.fetchone()
    finally:
        conn.close()


def find_products(min_price):
    conn = get_connection()
    try:
        with conn:                                    # commits on exit, rolls back on exception
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, name, price FROM product WHERE price >= %s",
                    (min_price,),                     # ← tuple, even for one param
                )
                return cur.fetchall()
    finally:
        conn.close()

if __name__ == "__main__":
    products = find_products(100)
    if not products:
        print("No products found.")
        pass
    
    for product in products:
        print(product)