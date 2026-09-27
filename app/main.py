from fastapi import APIRouter, FastAPI, Request
from fastapi.routing import APIRoute

from app.auth import origin_is_trusted
from app.db import DbCursor
from app.errors import error_response, register_error_handlers
from app.routers import (auth, customers, inventory, orders, products, promotions, reference, reports,
                         returns)


def operation_id(route: APIRoute) -> str:
    return route.name                   # e.g. "adjust_stock" instead of "adjust_stock_api_v1_stores_..."


app = FastAPI(title="JB Hi-Fi API", version="0.1.0", generate_unique_id_function=operation_id)
register_error_handlers(app)

# The session cookie is `SameSite=Lax`, which stops another site's POST from carrying it. This is the
# second line of the same defence (an old browser, or a client that ignores SameSite): a mutation that
# arrives with a browser `Origin` from somewhere else is refused before it reaches a route. A request with
# no `Origin` at all (curl, a test client, a server-to-server call) is not a browser session and is left
# alone — it still has to satisfy every permission check.
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def refuse_cross_origin_mutations(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method in MUTATING_METHODS and origin and not origin_is_trusted(origin, request.headers.get("host")):
        return error_response(403, "cross_origin_refused",
                              "That request came from another site, so it was refused.",
                              {"origin": origin})
    return await call_next(request)


api = APIRouter(prefix="/api/v1")
for module in (auth, reference, inventory, products, promotions, customers, orders, returns, reports):
    api.include_router(module.router)
app.include_router(api)


@app.get("/health")
def health(cur: DbCursor):
    cur.execute("SELECT current_database() AS db")
    return {"status": "ok", "db": cur.fetchone()["db"]}
