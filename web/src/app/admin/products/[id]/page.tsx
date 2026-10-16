"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { canEditCatalogue, useStaff } from "@/components/admin/staff-gate";
import { Cell, Row, Table } from "@/components/admin/table";
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
  const canEdit = canEditCatalogue(useStaff());
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
        {product.error ? <ErrorBox error={product.error} /> : <div className="h-40 animate-pulse rounded-card bg-sand" />}
      </>
    );
  }

  const saved = (updated: ProductDetail, what: string) => {
    product.setData(() => updated);
    showSuccess(<>{what} saved.</>);
  };

  return (
    <>
      <title>{`${p.name} · TechLight Admin`}</title>
      <BackLink name={p.name} />
      <PageHeader
        title={`${p.brand} ${p.name}`}
        description={<span className="inline-flex flex-wrap items-center gap-2">
          <span className="font-mono">{p.sku}</span> · {p.category}
          {p.on_sale && <Badge tone="sale">on sale</Badge>} {!p.is_active && <Badge>retired</Badge>}
        </span>}
      />
      <NoticeBanner notice={notice} onClose={clear} />

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
        {/* Keyed on the saved values, so the form resets to them after each save. */}
        <DetailsForm key={JSON.stringify([p.name, p.brand_id, p.category_id, p.base_price, p.is_active])}
          product={p} brands={brands.data ?? []} categories={categories.data ?? []} readOnly={!canEdit}
          onSaved={(updated) => saved(updated, "Details")} />

        <SpecsEditor key={JSON.stringify(p.specs)} productId={p.product_id} specs={p.specs} readOnly={!canEdit}
          onSaved={(specs) => saved({ ...p, specs }, "Specifications")} />

        <Card title={<>Stock by location <span className="font-sans font-normal text-muted">· {p.total_stock} in total</span></>}
          actions={<Link href="/admin/inventory" className="text-sm font-semibold text-brand-strong hover:underline">Adjust in Inventory →</Link>}>
          <Table label={`Stock of ${p.name} by location`}
            columns={["Location", "State", { label: "On hand", align: "right" }]}>
            {p.stock.map((s) => (
              <Row key={s.store_id}>
                <Cell>
                  <span className="font-semibold">{s.store_name}</span>{" "}
                  {s.store_type === "warehouse" && <Badge tone="blue">warehouse</Badge>}
                </Cell>
                <Cell className="text-muted">{s.state}</Cell>
                <Cell align="right"><StockBadge quantity={s.quantity} /></Cell>
              </Row>
            ))}
          </Table>
        </Card>

        <Card title="Promotions"
          actions={<Link href="/admin/promotions" className="text-sm font-semibold text-brand-strong hover:underline">Manage →</Link>}>
          {p.promotions.length === 0 ? <Empty>No promotions for this product.</Empty> : (
            <ul className="divide-y divide-line">
              {p.promotions.map((pr) => (
                <li key={pr.promotion_id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                  <div>
                    <span className="font-display text-base font-bold tabular-nums">{money(pr.sale_price)}</span>
                    <span className="ml-2 text-xs tabular-nums text-muted">
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

function BackLink({ name }: { name?: string }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-3 text-sm text-muted">
      <Link href="/admin/products" className="font-semibold text-brand-strong hover:underline">Products</Link>
      {name && <><span aria-hidden="true"> / </span>{name}</>}
    </nav>
  );
}

function DetailsForm({ product, brands, categories, readOnly, onSaved }: {
  product: ProductDetail;
  brands: Brand[];
  categories: Category[];
  readOnly: boolean;
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
    <Card title="Details" actions={readOnly ? undefined : (
      <Button tone="primary" size="sm" disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save"}</Button>
    )}>
      {/* A disabled fieldset disables every input inside it: read-only for staff who may not edit. */}
      <fieldset disabled={readOnly} className="space-y-4 p-5">
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
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)}
                className="h-4 w-4 shrink-0 accent-brand-strong" />
              Active (uncheck to retire — products are never deleted)
            </label>
          </Field>
        </div>
        {error && <ErrorBox error={error} />}
      </fieldset>
    </Card>
  );
}

function SpecsEditor({ productId, specs, readOnly, onSaved }: {
  productId: number;
  specs: Spec[];
  readOnly: boolean;
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
    <Card title="Specifications" actions={readOnly ? undefined : (
      <div className="flex gap-2">
        <Button size="sm" onClick={() => setRows((list) => [...list, { spec_name: "", spec_value: "", id: Date.now() }])}>
          Add row
        </Button>
        <Button tone="primary" size="sm" disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save"}</Button>
      </div>
    )}>
      <fieldset disabled={readOnly} className="space-y-2 p-5">
        {rows.length === 0 && <p className="text-sm text-muted">No specs yet.</p>}
        {rows.map((r) => (
          <div key={r.id} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-2">
            <input className={inputClass} placeholder="Name, e.g. Screen size" value={r.spec_name}
              onChange={(e) => update(r.id, "spec_name", e.target.value)} />
            <input className={inputClass} placeholder="Value" value={r.spec_value}
              onChange={(e) => update(r.id, "spec_value", e.target.value)} />
            <Button tone="ghost" aria-label="Remove" onClick={() => setRows((list) => list.filter((x) => x.id !== r.id))}>
              ×
            </Button>
          </div>
        ))}
        <p className="pt-1 text-xs text-muted">
          Saved as key–value rows in <code className="font-mono">product_spec</code>, key (product_id, spec_name): one value per name.
        </p>
        {error && <ErrorBox error={error} />}
      </fieldset>
    </Card>
  );
}
