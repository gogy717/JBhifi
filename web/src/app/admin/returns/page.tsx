"use client";

import Link from "next/link";
import { useState } from "react";

import { useAdminSession } from "@/components/admin/session";
import { StatusBadge } from "@/components/shop/order-timeline";
import { Button, Card, Empty, ErrorBox, Field, inputClass, PageHeader, selectClass } from "@/components/ui";
import { api, call, type ReturnStatus } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const STATUSES: ReturnStatus[] = ["requested", "received", "refunded", "rejected"];

export default function AdminReturnsPage() {
  const { session, signedIn } = useAdminSession();
  const [chosenStore, setChosenStore] = useState<number>();
  const [status, setStatus] = useState<string>("");
  const [lookup, setLookup] = useState("");
  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));

  const retailStores = (stores.data ?? []).filter((row) => row.store_type === "retail");
  const storeId = chosenStore ?? session?.store_id ?? retailStores[0]?.store_id;
  const queue = useLoad(`store-returns:${storeId}:${status}:${signedIn ? "staff" : "guest"}`, () =>
    !signedIn || storeId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/stores/{store_id}/returns", {
        params: {
          path: { store_id: storeId },
          query: { status: (status || undefined) as ReturnStatus | undefined },
        },
      })));

  const rows = queue.data ?? [];

  return (
    <>
      <title>Returns · JB Admin</title>
      <PageHeader title="Returns desk"
        description={<>Requests to take in at this store, and the ones it has already taken in. Receiving
          only records the item; restocking and refunding happen together when the return is processed.</>} />

      <Card className="mb-4">
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Store" hint={session?.staff_type === "support"
            ? "Support may read any store's desk."
            : undefined}>
            <select className={selectClass} value={storeId ?? ""} aria-label="Store"
              onChange={(event) => setChosenStore(Number(event.target.value))}>
              {(stores.data ?? []).map((row) => (
                <option key={row.store_id} value={row.store_id}>
                  {row.name}{row.store_type === "warehouse" ? " (warehouse)" : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Status">
            <select className={selectClass} value={status} aria-label="Status"
              onChange={(event) => setStatus(event.target.value)}>
              <option value="">Any status</option>
              {STATUSES.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </Field>
          <Field label="Look up a return by id">
            <input className={inputClass} value={lookup} inputMode="numeric" placeholder="e.g. 12"
              onChange={(event) => setLookup(event.target.value.replace(/\D/g, ""))} />
          </Field>
          <div className="flex items-end">
            {lookup
              ? (
                <Link href={`/admin/returns/${lookup}`}
                  className="inline-flex h-9 items-center rounded-md bg-neutral-900 px-3.5 text-sm font-medium text-white hover:bg-neutral-700">
                  Open return #{lookup}
                </Link>
              )
              : <p className="text-sm text-neutral-600">
                {rows.length} {rows.length === 1 ? "return" : "returns"}
              </p>}
          </div>
        </div>
      </Card>

      {!signedIn && (
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Sign in above as staff to work the desk. A customer can hand an item back at any retail store, so
          a return can appear here even when the order was fulfilled elsewhere.
        </p>
      )}

      {(queue.error ?? stores.error) && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <ErrorBox error={(queue.error ?? stores.error)!} />
          <Button onClick={() => { queue.reload(); stores.reload(); }}>Try again</Button>
        </div>
      )}

      {(queue.error ?? stores.error) === undefined && (
        <Card>
          {rows.length === 0
            ? <Empty>{queue.loading || !signedIn ? "Loading…" : "Nothing on the desk in this view."}</Empty>
            : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
                    <tr>
                      <th className="px-4 py-2 font-medium">Return</th>
                      <th className="px-4 py-2 font-medium">Order</th>
                      <th className="px-4 py-2 font-medium">Requested</th>
                      <th className="px-4 py-2 font-medium">Reason</th>
                      <th className="px-4 py-2 text-right font-medium">Refund</th>
                      <th className="px-4 py-2 font-medium">Status</th>
                      <th className="px-4 py-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-100">
                    {rows.map((row) => (
                      <tr key={row.return_id} className="hover:bg-neutral-50">
                        <td className="px-4 py-2.5 font-medium">#{row.return_id}</td>
                        <td className="px-4 py-2.5 text-neutral-600">#{row.order_id}</td>
                        <td className="px-4 py-2.5 text-neutral-600">{formatDateTime(row.requested_at)}</td>
                        <td className="max-w-[16rem] truncate px-4 py-2.5 text-neutral-600">{row.reason}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums">
                          {row.refund_amount ? money(row.refund_amount) : "—"}
                        </td>
                        <td className="px-4 py-2.5"><StatusBadge status={row.status} /></td>
                        <td className="px-4 py-2.5 text-right">
                          <Link href={`/admin/returns/${row.return_id}`}
                            className="text-sm font-medium hover:underline">Open</Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
        </Card>
      )}
    </>
  );
}
