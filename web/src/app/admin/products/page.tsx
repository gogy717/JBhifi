"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useDeferredValue, useState } from "react";

import { CategorySelect } from "@/components/category-select";
import { useAdminSession } from "@/components/admin/session";
import {
  Badge, Button, Card, Empty, ErrorBox, Field, inputClass, Modal, PageHeader, selectClass,
} from "@/components/ui";
import { type ApiError, api, type Brand, call, type Category, toApiError } from "@/lib/api/client";
import { money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function ProductsPage() {
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const [categoryId, setCategoryId] = useState<number>();
  const [brandId, setBrandId] = useState<number>();
  const [includeRetired, setIncludeRetired] = useState(false);
  const [creating, setCreating] = useState(false);
  const { session, signedIn } = useAdminSession();
  // Catalogue writes are for a store manager or support staff (the API enforces it as well).
  const canEdit = signedIn && (session?.staff_type === "support" || session?.runs_store === true);

  const brands = useLoad("brands", () => call(api.GET("/api/v1/brands")));
  const categories = useLoad("categories", () => call(api.GET("/api/v1/categories")));
  const products = useLoad(`products:${q}:${categoryId}:${brandId}:${includeRetired}`, () =>
    call(api.GET("/api/v1/products", {
      params: { query: { q: q || undefined, category_id: categoryId, brand_id: brandId, include_inactive: includeRetired } },
    })));
  const rows = products.data ?? [];

  return (
    <>
      <title>Products · JB Admin</title>
      <PageHeader
        title="Products"
        description={<>
          The catalogue: one row per SKU. “Current” is the price right now, read from the view
          <code className="mx-1 rounded bg-neutral-100 px-1 text-xs">v_product_current_price</code>
          (base price, or the sale price while a promotion runs).
        </>}
        actions={<Button tone="primary" disabled={!canEdit} onClick={() => setCreating(true)}>New product</Button>}
      />

      <Card className="mb-4">
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Search">
            <input className={inputClass} placeholder="Name, SKU or brand" value={search}
              onChange={(e) => setSearch(e.target.value)} />
          </Field>
          <Field label="Category">
            <CategorySelect categories={categories.data ?? []} value={categoryId} onChange={setCategoryId}
              allLabel="All categories" disabled={categories.error !== undefined} />
          </Field>
          <Field label="Brand">
            <select className={selectClass} value={brandId ?? ""} disabled={brands.error !== undefined}
              onChange={(e) => setBrandId(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">All brands</option>
              {(brands.data ?? []).map((b) => <option key={b.brand_id} value={b.brand_id}>{b.name}</option>)}
            </select>
          </Field>
          <label className="flex items-end gap-2 pb-2 text-sm text-neutral-700">
            <input type="checkbox" checked={includeRetired} onChange={(e) => setIncludeRetired(e.target.checked)}
              className="h-4 w-4 accent-neutral-900" />
            Show retired products
          </label>
        </div>
        {(brands.error || categories.error) && (
          <ErrorBox error={(brands.error ?? categories.error)!} className="mx-4 mb-4"
            onRetry={() => { brands.reload(); categories.reload(); }} />
        )}
      </Card>

      <Card title={<>{rows.length} products</>}>
        {products.error && <ErrorBox error={products.error} className="m-4" />}
        {!products.error && rows.length === 0 && <Empty>{products.loading ? "Loading…" : "No products match."}</Empty>}
        {rows.length > 0 && (
          <div className={`overflow-x-auto ${products.loading ? "opacity-60" : ""}`}>
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Product</th>
                  <th className="px-4 py-2 font-medium">Category</th>
                  <th className="px-4 py-2 text-right font-medium">Base</th>
                  <th className="px-4 py-2 text-right font-medium">Current</th>
                  <th className="px-4 py-2 text-right font-medium">Stock (all)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {rows.map((p) => (
                  <tr key={p.product_id} className="hover:bg-neutral-50">
                    <td className="px-4 py-2.5">
                      <Link href={`/admin/products/${p.product_id}`} className="font-medium text-neutral-900 hover:underline">
                        {p.name}
                      </Link>{" "}
                      {!p.is_active && <Badge>retired</Badge>}
                      <div className="text-xs text-neutral-500">
                        {p.brand} · <span className="font-mono">{p.sku}</span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-neutral-600">{p.category}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-neutral-600">{money(p.base_price)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      {p.on_sale && <span className="mr-1.5"><Badge tone="sale">sale</Badge></span>}
                      <span className={p.on_sale ? "font-semibold" : ""}>{money(p.current_price)}</span>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{p.total_stock}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
      <p className="text-xs text-neutral-500">
        The SKU format, unique SKU and non-negative price are checked by the database, not here — try breaking them.
      </p>
      {error && <ErrorBox error={error} />}
    </Modal>
  );
}
