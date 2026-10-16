"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useDeferredValue, useState } from "react";

import { SearchIcon } from "@/components/admin/icons";
import { canEditCatalogue, useStaff } from "@/components/admin/staff-gate";
import { Cell, ProductName, Row, Table } from "@/components/admin/table";
import { CategorySelect } from "@/components/category-select";
import {
  Badge, Button, Card, Empty, ErrorBox, Field, inputClass, Modal, PageHeader, selectClass,
} from "@/components/ui";
import { type ApiError, api, type Brand, call, type Category, toApiError } from "@/lib/api/client";
import { money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function ProductsPage() {
  const canEdit = canEditCatalogue(useStaff());
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const [categoryId, setCategoryId] = useState<number>();
  const [brandId, setBrandId] = useState<number>();
  const [includeRetired, setIncludeRetired] = useState(false);
  const [creating, setCreating] = useState(false);

  const brands = useLoad("brands", () => call(api.GET("/api/v1/brands")));
  const categories = useLoad("categories", () => call(api.GET("/api/v1/categories")));
  const products = useLoad(`products:${q}:${categoryId}:${brandId}:${includeRetired}`, () =>
    call(api.GET("/api/v1/products", {
      params: { query: { q: q || undefined, category_id: categoryId, brand_id: brandId, include_inactive: includeRetired } },
    })));
  const rows = products.data ?? [];

  return (
    <>
      <title>Products · TechLight Admin</title>
      <PageHeader
        title="Products"
        description={<>
          The catalogue: one row per SKU. “Current” is the price right now, read from the view
          <code className="mx-1 rounded bg-sand px-1.5 py-0.5 font-mono text-xs">v_product_current_price</code>
          (base price, or the sale price while a promotion runs).
        </>}
        actions={canEdit ? <Button tone="primary" onClick={() => setCreating(true)}>New product</Button> : undefined}
      />

      <Card className="mb-5">
        <div className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_repeat(2,minmax(0,1fr))_auto] lg:items-end">
          <Field label="Search">
            <span className="relative block">
              <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
              <input className={`${inputClass} pl-10`} placeholder="Name, SKU or brand" value={search}
                onChange={(e) => setSearch(e.target.value)} />
            </span>
          </Field>
          <Field label="Category">
            <CategorySelect categories={categories.data ?? []} value={categoryId} onChange={setCategoryId}
              allLabel="All categories" />
          </Field>
          <Field label="Brand">
            <select className={selectClass} value={brandId ?? ""}
              onChange={(e) => setBrandId(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">All brands</option>
              {(brands.data ?? []).map((b) => <option key={b.brand_id} value={b.brand_id}>{b.name}</option>)}
            </select>
          </Field>
          <label className="flex h-11 cursor-pointer items-center gap-2 self-end rounded-full border border-line px-4
            text-sm font-semibold has-checked:border-ink has-checked:bg-ink has-checked:text-white">
            <input type="checkbox" checked={includeRetired} onChange={(e) => setIncludeRetired(e.target.checked)}
              className="h-4 w-4 accent-brand-strong" />
            Show retired products
          </label>
        </div>
      </Card>

      <Card>
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
          <span className="font-display text-base font-bold">Catalogue</span>
          <span className="text-sm text-muted"><span className="tabular-nums">{rows.length}</span> products</span>
        </div>
        {products.error && <ErrorBox error={products.error} className="m-5" />}
        {!products.error && rows.length === 0 && <Empty>{products.loading ? "Loading…" : "No products match."}</Empty>}
        {rows.length > 0 && (
          <Table label="Products" loading={products.loading}
            columns={["Product", "Category", { label: "Base", align: "right" }, { label: "Current", align: "right" },
              { label: "Stock (all)", align: "right" }]}>
            {rows.map((p) => (
              <Row key={p.product_id}>
                <Cell>
                  <ProductName brand={p.brand} sku={p.sku} name={
                    <Link href={`/admin/products/${p.product_id}`} className="hover:text-brand-strong hover:underline">
                      {p.name}
                    </Link>}>
                    {!p.is_active && <span className="ml-2"><Badge>retired</Badge></span>}
                  </ProductName>
                </Cell>
                <Cell className="text-muted">{p.category}</Cell>
                <Cell numeric className="text-muted">{money(p.base_price)}</Cell>
                <Cell numeric>
                  {p.on_sale && <span className="mr-1.5"><Badge tone="sale">sale</Badge></span>}
                  <span className={p.on_sale ? "font-semibold text-brand-strong" : ""}>{money(p.current_price)}</span>
                </Cell>
                <Cell numeric>{p.total_stock}</Cell>
              </Row>
            ))}
          </Table>
        )}
      </Card>

      {creating && (
        <NewProductDialog brands={brands.data ?? []} categories={categories.data ?? []}
          onClose={() => setCreating(false)} />
      )}
    </>
  );
}

function NewProductDialog({ brands, categories, onClose }: {
  brands: Brand[];
  categories: Category[];
  onClose: () => void;
}) {
  const router = useRouter();
  const [form, setForm] = useState({ sku: "", name: "", brandId: "", categoryId: "", basePrice: "" });
  const [error, setError] = useState<ApiError>();
  const [saving, setSaving] = useState(false);
  const complete = form.sku && form.name && form.brandId && form.categoryId && form.basePrice;

  const set = (field: keyof typeof form) => (value: string) => setForm((f) => ({ ...f, [field]: value }));

  async function save() {
    setSaving(true);
    try {
      const product = await call(api.POST("/api/v1/products", {
        body: {
          sku: form.sku.trim(), name: form.name.trim(), brand_id: Number(form.brandId),
          category_id: Number(form.categoryId), base_price: form.basePrice.trim(),
        },
      }));
      router.push(`/admin/products/${product.product_id}`);
    } catch (e) {
      setError(toApiError(e));
      setSaving(false);
    }
  }

  return (
    <Modal title="New product" onClose={onClose} footer={<>
      <Button onClick={onClose}>Cancel</Button>
      <Button tone="primary" disabled={!complete || saving} onClick={save}>{saving ? "Creating…" : "Create"}</Button>
    </>}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="SKU" hint="Upper case, e.g. SONY-WH1000XM6-B">
          <input className={`${inputClass} font-mono`} value={form.sku} onChange={(e) => set("sku")(e.target.value)} />
        </Field>
        <Field label="Base price (AUD)">
          <input className={inputClass} inputMode="decimal" placeholder="0.00" value={form.basePrice}
            onChange={(e) => set("basePrice")(e.target.value)} />
        </Field>
      </div>
      <Field label="Name" hint="Without the brand — the brand is its own column.">
        <input className={inputClass} value={form.name} onChange={(e) => set("name")(e.target.value)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Brand">
          <select className={selectClass} value={form.brandId} onChange={(e) => set("brandId")(e.target.value)}>
            <option value="">Choose…</option>
            {brands.map((b) => <option key={b.brand_id} value={b.brand_id}>{b.name}</option>)}
          </select>
        </Field>
        <Field label="Category">
          <CategorySelect categories={categories} leavesOnly value={form.categoryId ? Number(form.categoryId) : undefined}
            onChange={(id) => set("categoryId")(id === undefined ? "" : String(id))} allLabel="Choose…" />
        </Field>
      </div>
      <p className="text-xs text-muted">
        The SKU format, unique SKU and non-negative price are checked by the database, not here — try breaking them.
      </p>
      {error && <ErrorBox error={error} />}
    </Modal>
  );
}
