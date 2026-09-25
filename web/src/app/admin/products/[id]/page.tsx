"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { CategorySelect } from "@/components/category-select";
import {
  Badge, Button, Card, Empty, ErrorBox, Field, inputClass, NoticeBanner, PageHeader, selectClass, StockBadge,
  useNotice,
} from "@/components/ui";
import {
  type ApiError, api, type Brand, call, type Category, type ProductDetail, type Spec, toApiError,
} from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const STATUS_TONE = { active: "green", upcoming: "blue", ended: "neutral" } as const;

export default function ProductPage() {
  const productId = Number(useParams<{ id: string }>().id);
  const { notice, showSuccess, clear } = useNotice();
  const brands = useLoad("brands", () => call(api.GET("/api/v1/brands")));
  const categories = useLoad("categories", () => call(api.GET("/api/v1/categories")));
  const product = useLoad(`product:${productId}`, () =>
    call(api.GET("/api/v1/products/{product_id}", { params: { path: { product_id: productId } } })));
  const p = product.data;

  if (!p) {
    return (
      <>
        <BackLink />
        {product.error ? <ErrorBox error={product.error} /> : <p className="text-sm text-neutral-500">Loading…</p>}
      </>
    );
  }

  const saved = (updated: ProductDetail, what: string) => {
    product.setData(() => updated);
    showSuccess(<>{what} saved.</>);
  };

  return (
    <>
      <title>{`${p.name} · JB Admin`}</title>
      <BackLink />
      <PageHeader
        title={`${p.brand} ${p.name}`}
        description={<>
          <span className="font-mono">{p.sku}</span> · {p.category}{" "}
          {p.on_sale && <Badge tone="sale">on sale</Badge>} {!p.is_active && <Badge>retired</Badge>}
        </>}
      />
      <NoticeBanner notice={notice} onClose={clear} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Keyed on the saved values, so the form resets to them after each save. */}
        <DetailsForm key={JSON.stringify([p.name, p.brand_id, p.category_id, p.base_price, p.is_active])}
          product={p} brands={brands.data ?? []} categories={categories.data ?? []}
          onSaved={(updated) => saved(updated, "Details")} />

        <SpecsEditor key={JSON.stringify(p.specs)} productId={p.product_id} specs={p.specs}
          onSaved={(specs) => saved({ ...p, specs }, "Specifications")} />

        <Card title={<>Stock by location <span className="font-normal text-neutral-500">· {p.total_stock} in total</span></>}
          actions={<Link href="/admin/inventory" className="text-xs text-neutral-600 hover:underline">Adjust in Inventory →</Link>}>
          <table className="w-full text-sm">
            <tbody className="divide-y divide-neutral-100">
              {p.stock.map((s) => (
                <tr key={s.store_id}>
                  <td className="px-4 py-2">
                    {s.store_name} {s.store_type === "warehouse" && <Badge tone="blue">warehouse</Badge>}
                  </td>
                  <td className="px-4 py-2 text-neutral-500">{s.state}</td>
                  <td className="px-4 py-2 text-right"><StockBadge quantity={s.quantity} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="Promotions"
          actions={<Link href="/admin/promotions" className="text-xs text-neutral-600 hover:underline">Manage →</Link>}>
          {p.promotions.length === 0 ? <Empty>No promotions for this product.</Empty> : (
            <ul className="divide-y divide-neutral-100">
              {p.promotions.map((pr) => (
                <li key={pr.promotion_id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                  <div>
                    <span className="font-semibold">{money(pr.sale_price)}</span>
                    <span className="ml-2 text-xs text-neutral-500">
                      {formatDateTime(pr.starts_at)} → {formatDateTime(pr.ends_at)}
                    </span>
                  </div>
                  <Badge tone={STATUS_TONE[pr.status]}>{pr.status}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

function BackLink() {
  return <Link href="/admin/products" className="mb-3 inline-block text-sm text-neutral-600 hover:underline">← Products</Link>;
}

function DetailsForm({ product, brands, categories, onSaved }: {
  product: ProductDetail;
  brands: Brand[];
  categories: Category[];
  onSaved: (product: ProductDetail) => void;
}) {
  const [name, setName] = useState(product.name);
  const [brandId, setBrandId] = useState(product.brand_id);
  const [categoryId, setCategoryId] = useState(product.category_id);
  const [basePrice, setBasePrice] = useState(product.base_price);
  const [active, setActive] = useState(product.is_active);
  const [error, setError] = useState<ApiError>();
  const [saving, setSaving] = useState(false);

  // PATCH only what changed.
  const changes = {
    ...(name.trim() !== product.name && { name: name.trim() }),
    ...(brandId !== product.brand_id && { brand_id: brandId }),
    ...(categoryId !== product.category_id && { category_id: categoryId }),
    ...(basePrice.trim() !== product.base_price && { base_price: basePrice.trim() }),
    ...(active !== product.is_active && { is_active: active }),
  };
  const dirty = Object.keys(changes).length > 0;

  async function save() {
    setSaving(true);
    setError(undefined);
    try {
      onSaved(await call(api.PATCH("/api/v1/products/{product_id}", {
        params: { path: { product_id: product.product_id } }, body: changes,
      })));
    } catch (e) {
      setError(toApiError(e));
      setSaving(false);
    }
  }

  return (
    <Card title="Details" actions={
      <Button tone="primary" size="sm" disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save"}</Button>
    }>
      <div className="space-y-3 p-4">
        <Field label="Name">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Brand">
            <select className={selectClass} value={brandId} onChange={(e) => setBrandId(Number(e.target.value))}>
              {brands.map((b) => <option key={b.brand_id} value={b.brand_id}>{b.name}</option>)}
            </select>
          </Field>
          <Field label="Category">
            <CategorySelect categories={categories} leavesOnly value={categoryId}
              onChange={(id) => id !== undefined && setCategoryId(id)} allLabel="Choose…" />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Base price (AUD)"
            hint={product.on_sale ? <>Now selling at {money(product.current_price)} (promotion).</> : undefined}>
            <input className={inputClass} inputMode="decimal" value={basePrice}
              onChange={(e) => setBasePrice(e.target.value)} />
          </Field>
          <Field label="Status">
            <label className="flex h-9 items-center gap-2 text-sm">
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)}
                className="h-4 w-4 accent-neutral-900" />
              Active (uncheck to retire — products are never deleted)
            </label>
          </Field>
        </div>
        {error && <ErrorBox error={error} />}
      </div>
    </Card>
  );
}

function SpecsEditor({ productId, specs, onSaved }: {
  productId: number;
  specs: Spec[];
  onSaved: (specs: Spec[]) => void;
}) {
  const [rows, setRows] = useState(specs.map((s, i) => ({ ...s, id: i })));
  const [error, setError] = useState<ApiError>();
  const [saving, setSaving] = useState(false);
  const dirty = JSON.stringify(rows.map(({ spec_name, spec_value }) => ({ spec_name, spec_value }))) !== JSON.stringify(specs);

  const update = (id: number, field: "spec_name" | "spec_value", value: string) =>
    setRows((list) => list.map((r) => (r.id === id ? { ...r, [field]: value } : r)));

  async function save() {
    setSaving(true);
    setError(undefined);
    try {
      const body = rows
        .map((r) => ({ spec_name: r.spec_name.trim(), spec_value: r.spec_value.trim() }))
        .filter((r) => r.spec_name || r.spec_value);
      onSaved(await call(api.PUT("/api/v1/products/{product_id}/specs", {
        params: { path: { product_id: productId } }, body,
      })));
    } catch (e) {
      setError(toApiError(e));
      setSaving(false);
    }
  }

  return (
    <Card title="Specifications" actions={
      <div className="flex gap-2">
        <Button size="sm" onClick={() => setRows((list) => [...list, { spec_name: "", spec_value: "", id: Date.now() }])}>
          Add row
        </Button>
        <Button tone="primary" size="sm" disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save"}</Button>
      </div>
    }>
      <div className="space-y-2 p-4">
        {rows.length === 0 && <p className="text-sm text-neutral-500">No specs yet.</p>}
        {rows.map((r) => (
          <div key={r.id} className="grid grid-cols-[1fr_1fr_auto] gap-2">
            <input className={inputClass} placeholder="Name, e.g. Screen size" value={r.spec_name}
              onChange={(e) => update(r.id, "spec_name", e.target.value)} />
            <input className={inputClass} placeholder="Value" value={r.spec_value}
              onChange={(e) => update(r.id, "spec_value", e.target.value)} />
            <Button tone="ghost" aria-label="Remove" onClick={() => setRows((list) => list.filter((x) => x.id !== r.id))}>
              ×
            </Button>
          </div>
        ))}
        <p className="pt-1 text-xs text-neutral-500">
          Saved as key–value rows in <code>product_spec</code>, key (product_id, spec_name): one value per name.
        </p>
        {error && <ErrorBox error={error} />}
      </div>
    </Card>
  );
}
