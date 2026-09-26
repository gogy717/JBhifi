from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from app.db import DbCursor
from app.errors import register_error_handlers
from app.routers import auth, customers, inventory, orders, products, promotions, reference


def operation_id(route: APIRoute) -> str:
    return route.name                   # e.g. "adjust_stock" instead of "adjust_stock_api_v1_stores_..."


app = FastAPI(title="JB Hi-Fi API", version="0.1.0", generate_unique_id_function=operation_id)
register_error_handlers(app)

api = APIRouter(prefix="/api/v1")
for module in (auth, reference, inventory, products, promotions, customers, orders):
    api.include_router(module.router)
app.include_router(api)


@app.get("/health")
def health(cur: DbCursor):
    cur.execute("SELECT current_database() AS db")
    return {"status": "ok", "db": cur.fetchone()["db"]}
