from fastapi import APIRouter

from app.db import DbCursor
from app.errors import ERROR_RESPONSES
from app.schemas.reference import BrandOut, CategoryOut, StaffOut, StoreOut
from app.services import reference

router = APIRouter(tags=["reference"], responses=ERROR_RESPONSES)


@router.get("/stores", response_model=list[StoreOut])
def list_stores(cur: DbCursor):
    return reference.list_stores(cur)


@router.get("/staff", response_model=list[StaffOut])
def list_staff(cur: DbCursor, store_id: int | None = None):
    return reference.list_staff(cur, store_id)


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(cur: DbCursor):
    return reference.list_categories(cur)


@router.get("/brands", response_model=list[BrandOut])
def list_brands(cur: DbCursor):
    return reference.list_brands(cur)
