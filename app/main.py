from fastapi import FastAPI

from app.db import DbCursor
from app.routers import products

app = FastAPI(title="JB Hi-Fi API")
app.include_router(products.router)


@app.get("/health")
def health(cur: DbCursor):
    cur.execute("SELECT current_database() AS db")
    return {"status": "ok", "db": cur.fetchone()["db"]}