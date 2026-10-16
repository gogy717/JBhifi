"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useStaff } from "@/components/admin/staff-gate";
import { RETURN_STATUS_TEXT, ReturnStatusBadge } from "@/components/return-status";
import { Button, Card, Empty, ErrorBox, Field, inputClass, PageHeader, selectClass } from "@/components/ui";
import { api, call, type Store } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function ReturnsDeskPage() {
  const me = useStaff();
  const router = useRouter();
  // Store staff work their own store's desk; support staff can look at any store's.
  const ownStore = me.staff_type === "store";
  const [storeId, setStoreId] = useState(me.store_id ?? 1);
  const [status, setStatus] = useState("");
  const [lookup, setLookup] = useState("");

  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));
  const desk = useLoad(`returns-desk:${storeId}`, () =>
    call(api.GET("/api/v1/stores/{store_id}/returns", { params: { path: { store_id: storeId } } })));
  const store = stores.data?.find((s) => s.store_id === storeId);
  const rows = (desk.data ?? []).filter((row) => !status || row.status === status);
  const lookupId = Number(lookup.trim().replace(/^#/, ""));

  return (
    <>
      <title>Returns · TechLight Admin</title>
      <PageHeader
        title="Returns"
        description={<>
          Customers ask for returns online, within 30 days of getting their order (BR11), and bring the items to any
          retail store (BR22). Receive them here, check them, then refund — restock and refund in one transaction
          (T2) — or reject them with a reason.
        </>}
      />

      <Card className="mb-4">
        <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
          <Field label="Store">
            {ownStore
              ? <p className="flex h-9 items-center text-sm font-medium">{store?.name ?? me.store_name ?? "…"}</p>
              : <StoreSelect stores={stores.data ?? []} value={storeId} onChange={setStoreId} />}
          </Field>
          <Field label="Status">
            <select className={selectClass} value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">All</option>
              {Object.entries(RETURN_STATUS_TEXT).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </Field>
          <Field label="Find return #" hint="A customer can bring a return asked for on any order to any retail store.">
            <form className="flex gap-2" onSubmit={(event) => {
              event.preventDefault();
              if (Number.isInteger(lookupId) && lookupId > 0) router.push(`/admin/returns/${lookupId}`);
            }}>
              <input className={inputClass} inputMode="numeric" placeholder="e.g. 42" value={lookup}
                onChange={(event) => setLookup(event.target.value)} />
              <Button type="submit" disabled={!(Number.isInteger(lookupId) && lookupId > 0)}>Open</Button>
            </form>
          </Field>
        </div>
      </Card>

      <Card title={`Desk at ${store?.name ?? "…"}`}
        actions={<span className="text-xs text-neutral-500">requested returns of this store&apos;s orders, and every return received here</span>}>
        {desk.error ? (
          <div className="flex flex-wrap items-center gap-3 p-4">
            <ErrorBox error={desk.error} />
            <Button onClick={desk.reload}>Try again</Button>
          </div>
        ) : !desk.data ? <div className="m-4 h-24 animate-pulse rounded bg-neutral-100" />
          : rows.length === 0 ? <Empty>No returns here{status && ` that are ${RETURN_STATUS_TEXT[status]?.toLowerCase()}`}.</Empty>
          : (
            <div className={`overflow-x-auto ${desk.loading ? "opacity-60" : ""}`}>
              <table className="w-full text-sm">
                <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <tr>
                    <th className="px-4 py-2 font-medium">Return</th>
                    <th className="px-4 py-2 font-medium">Items</th>
                    <th className="px-4 py-2 text-right font-medium">Worth</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium">Received at</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100">
                  {rows.map((row) => (
                    <tr key={row.return_id} className="hover:bg-neutral-50">
                      <td className="px-4 py-2.5">
                        <Link href={`/admin/returns/${row.return_id}`} className="font-medium hover:underline">
                          #{row.return_id}
                        </Link>
                        <div className="text-xs text-neutral-500">order #{row.order_id} · {formatDateTime(row.requested_at)}</div>
                      </td>
                      <td className="px-4 py-2.5 text-neutral-700">
                        {row.lines.map((line) => <div key={line.line_no}>{line.quantity} × {line.name}</div>)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2.5 text-right tabular-nums">{money(row.value)}</td>
                      <td className="px-4 py-2.5"><ReturnStatusBadge status={row.status} /></td>
                      <td className="px-4 py-2.5 text-neutral-600">{row.received_store_name ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
    </>
  );
}

function StoreSelect({ stores, value, onChange }: { stores: Store[]; value: number; onChange: (id: number) => void }) {
  return (
    <select className={selectClass} value={value} onChange={(event) => onChange(Number(event.target.value))}>
      {stores.map((s) => (
        <option key={s.store_id} value={s.store_id}>{s.name}{s.store_type === "warehouse" ? " (warehouse)" : ""}</option>
      ))}
    </select>
  );
}
