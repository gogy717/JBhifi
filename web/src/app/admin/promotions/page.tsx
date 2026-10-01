"use client";

import Link from "next/link";
import { useState } from "react";

import { canEditCatalogue, useStaff } from "@/components/admin/staff-gate";
import {
  Badge, Button, Card, Empty, ErrorBox, Field, inputClass, Modal, NoticeBanner, PageHeader, selectClass, useNotice,
} from "@/components/ui";
import {
  type ApiError, api, call, type ProductSummary, type Promotion, type PromotionStatus, toApiError,
} from "@/lib/api/client";
import { formatDateTime, money, percentOff } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const TABS: { value?: PromotionStatus; label: string }[] = [
  { label: "All" }, { value: "active", label: "Active" }, { value: "upcoming", label: "Upcoming" },
  { value: "ended", label: "Ended" },
];
const STATUS_TONE = { active: "green", upcoming: "blue", ended: "neutral" } as const;

export default function PromotionsPage() {
  const canEdit = canEditCatalogue(useStaff());
  const [status, setStatus] = useState<PromotionStatus>();
  const [creating, setCreating] = useState(false);
  const { notice, showError, showSuccess, clear } = useNotice();

  const promotions = useLoad(`promotions:${status}`, () =>
    call(api.GET("/api/v1/promotions", { params: { query: { status } } })));
  const products = useLoad("products", () => call(api.GET("/api/v1/products")));

  async function remove(promotion: Promotion) {
    try {
      await call(api.DELETE("/api/v1/promotions/{promotion_id}", {
        params: { path: { promotion_id: promotion.promotion_id } },
      }));
      promotions.setData((list) => list.filter((p) => p.promotion_id !== promotion.promotion_id));
      showSuccess(<>Deleted the {money(promotion.sale_price)} promotion on <b>{promotion.product_name}</b>.</>);
    } catch (e) {
      showError(toApiError(e));
    }
  }

  const rows = promotions.data ?? [];
  return (
    <>
      <title>Promotions · JB Admin</title>
      <PageHeader
        title="Promotions"
        description={<>
          A sale price for one product over a period. The database refuses a sale price that isn&apos;t below the
          base price, and two promotions for the same product that overlap in time (BR15, a trigger).
        </>}
        actions={canEdit ? <Button tone="primary" onClick={() => setCreating(true)}>New promotion</Button> : undefined}
      />
      <NoticeBanner notice={notice} onClose={clear} />

      <Card
        title={
          <div className="flex gap-1">
            {TABS.map((tab) => (
              <button key={tab.label} type="button" onClick={() => setStatus(tab.value)}
                className={`rounded-md px-2.5 py-1 text-sm ${
                  status === tab.value ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"}`}>
                {tab.label}
              </button>
            ))}
          </div>
        }
      >
        {promotions.error && <ErrorBox error={promotions.error} className="m-4" />}
        {!promotions.error && rows.length === 0 && (
          <Empty>{promotions.loading ? "Loading…" : "No promotions here."}</Empty>
        )}
        {rows.length > 0 && (
          <div className={`overflow-x-auto ${promotions.loading ? "opacity-60" : ""}`}>
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Product</th>
                  <th className="px-4 py-2 text-right font-medium">Base</th>
                  <th className="px-4 py-2 text-right font-medium">Sale</th>
                  <th className="px-4 py-2 font-medium">Runs</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {rows.map((p) => (
                  <tr key={p.promotion_id} className="hover:bg-neutral-50">
                    <td className="px-4 py-2.5">
                      <Link href={`/admin/products/${p.product_id}`} className="font-medium hover:underline">
                        {p.brand} {p.product_name}
                      </Link>
                      <div className="font-mono text-xs text-neutral-500">{p.sku}</div>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-neutral-600">{money(p.base_price)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">
                      <div className="font-semibold">{money(p.sale_price)}</div>
                      <div className="text-xs text-neutral-500">{percentOff(p.base_price, p.sale_price)}</div>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-neutral-600">
                      {formatDateTime(p.starts_at)}<br />→ {formatDateTime(p.ends_at)}
                    </td>
                    <td className="px-4 py-2.5"><Badge tone={STATUS_TONE[p.status]}>{p.status}</Badge></td>
                    <td className="px-4 py-2.5 text-right">{canEdit && <DeleteButton onConfirm={() => remove(p)} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {creating && (
        <NewPromotionDialog
          products={products.data ?? []}
          onClose={() => setCreating(false)}
          onCreated={(created) => {
            setCreating(false);
            promotions.reload();
            showSuccess(<>Created a {money(created.sale_price)} promotion on <b>{created.product_name}</b>.</>);
          }}
        />
      )}
    </>
  );
}

/** Two clicks instead of a browser confirm() dialog. */
function DeleteButton({ onConfirm }: { onConfirm: () => void }) {
  const [armed, setArmed] = useState(false);
  return armed ? (
    <span className="inline-flex gap-1">
      <Button size="sm" tone="danger" onClick={onConfirm}>Delete</Button>
      <Button size="sm" tone="ghost" onClick={() => setArmed(false)}>Keep</Button>
    </span>
  ) : (
    <Button size="sm" tone="ghost" onClick={() => setArmed(true)}>Delete…</Button>
  );
}

/** "YYYY-MM-DD" for a local date, as <input type="date"> wants it. */
function isoDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Local midnight at the start of the given day, `plusDays` later, as an ISO timestamp (with offset). */
function startOfDay(day: string, plusDays = 0): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y, m - 1, d + plusDays).toISOString();
}

function NewPromotionDialog({ products, onClose, onCreated }: {
  products: ProductSummary[];
  onClose: () => void;
  onCreated: (promotion: Promotion) => void;
}) {
  const [today] = useState(() => new Date());
  const [productId, setProductId] = useState("");
  const [salePrice, setSalePrice] = useState("");
  const [firstDay, setFirstDay] = useState(() => isoDay(today));
  const [lastDay, setLastDay] = useState(() => isoDay(new Date(today.getTime() + 6 * 86_400_000)));
  const [error, setError] = useState<ApiError>();
  const [saving, setSaving] = useState(false);
  const product = products.find((p) => p.product_id === Number(productId));
  const complete = productId && salePrice && firstDay && lastDay;
  const sorted = [...products].sort((a, b) => `${a.brand} ${a.name}`.localeCompare(`${b.brand} ${b.name}`));

  async function save() {
    setSaving(true);
    setError(undefined);
    try {
      onCreated(await call(api.POST("/api/v1/promotions", {
        body: {
          product_id: Number(productId),
          sale_price: salePrice.trim(),
          // The database stores a half-open period [starts_at, ends_at): the end is midnight after the last day.
          starts_at: startOfDay(firstDay),
          ends_at: startOfDay(lastDay, 1),
        },
      })));
    } catch (e) {
      setError(toApiError(e));
      setSaving(false);
    }
  }

  return (
    <Modal title="New promotion" onClose={onClose} footer={<>
      <Button onClick={onClose}>Cancel</Button>
      <Button tone="primary" disabled={!complete || saving} onClick={save}>{saving ? "Creating…" : "Create"}</Button>
    </>}>
      <Field label="Product">
        <select className={selectClass} value={productId} onChange={(e) => setProductId(e.target.value)}>
          <option value="">Choose…</option>
          {sorted.map((p) => (
            <option key={p.product_id} value={p.product_id}>{p.brand} {p.name} — {money(p.base_price)}</option>
          ))}
        </select>
      </Field>
      <Field label="Sale price (AUD)"
        hint={product ? <>Base price {money(product.base_price)}. The sale price must be lower (BR15).</> : undefined}>
        <input className={inputClass} inputMode="decimal" placeholder="0.00" value={salePrice}
          onChange={(e) => setSalePrice(e.target.value)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="First day">
          <input className={inputClass} type="date" value={firstDay} onChange={(e) => setFirstDay(e.target.value)} />
        </Field>
        <Field label="Last day">
          <input className={inputClass} type="date" value={lastDay} onChange={(e) => setLastDay(e.target.value)} />
        </Field>
      </div>
      <p className="text-xs text-neutral-500">
        Runs from the start of the first day to the end of the last day, in your time zone. It may not overlap
        another promotion for the same product — check the product&apos;s page for existing ones.
      </p>
      {error && <ErrorBox error={error} />}
    </Modal>
  );
}
