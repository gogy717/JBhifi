from pydantic import BaseModel


class StoreOut(BaseModel):
    store_id: int
    name: str
    store_type: str
    suburb: str
    state: str
    manager_id: int
    manager_name: str


class StaffOut(BaseModel):
    staff_id: int
    full_name: str
    staff_type: str
    store_id: int | None
    store_name: str | None
    is_manager: bool


class CategoryOut(BaseModel):
    category_id: int
    name: str
    parent_id: int | None
    parent_name: str | None


class BrandOut(BaseModel):
    brand_id: int
    name: str
