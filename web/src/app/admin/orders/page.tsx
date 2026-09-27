"use client";

import Link from "next/link";
import { useState } from "react";

import { useAdminSession } from "@/components/admin/session";
import { StatusBadge } from "@/components/shop/order-timeline";
import { Button, Card, Empty, ErrorBox, Field, PageHeader, selectClass } from "@/components/ui";
import { api, call, type OrderStatus } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

const STATUSES: OrderStatus[] = ["placed", "paid", "picking", "shipped", "delivered", "ready", "collected",
  "cancelled"];

export default function AdminOrdersPage() {
  const { session, signedIn } = useAdminSession();
  const [chosenStore, setChosenStore] = useState<number>();
  const [status, setStatus] = useState<string>("");
  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));

  // Store staff start on their own store; support staff (who have none) on the first retail store.
  const retailStores = (stores.data ?? []).filter((row) => row.store_type === "retail");
  const storeId = chosenStore ?? session?.store_id ?? retailStores[0]?.store_id;
  const queue = useLoad(`store-orders:${storeId}:${status}:${signedIn ? "staff" : "guest"}`, () =>
    !signedIn || storeId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/stores/{store_id}/orders", {
        params: { path: { store_id: storeId }, query: { status: (status || undefined) as OrderStatus | undefined } },
      })));

  const rows = queue.data ?? [];
  const store = (stores.data ?? []).find((row) => row.store_id === storeId);
  const canRead = signedIn && (session?.staff_type === "support" || session?.store_id === storeId);

  return (
    <>
      <title>Orders · JB Admin</title>
      <PageHeader title="Order queue"
        description={<>Orders this store is fulfilling, newest first. Every move is one transaction, and the
          database only accepts the transitions the fulfilment method allows (BR09).</>} />

      <Card className="mb-4">
        <div className="grid gap-3 p-4 sm:grid-cols-3">
          <Field label="Store" hint={session?.staff_type === "support"
            ? "Support may look at any store; only the store's staff can move its orders."
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
          <div className="flex items-end">
            <p className="text-sm text-neutral-600">
              {rows.length} {rows.length === 1 ? "order" : "orders"}
              {store ? ` for ${store.name}` : ""}
            </p>
          </div>
        </div>
      </Card>

      {!signedIn && (
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Sign in above as staff to see the queue.
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
            ? <Empty>{queue.loading || !signedIn ? "Loading…" : "No orders in this view."}</Empty>
            : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
                    <tr>
                      <th className="px-4 py-2 font-medium">Order</th>
                      <th className="px-4 py-2 font-medium">Placed</th>
                      <th className="px-4 py-2 font-medium">Fulfilment</th>
                      <th className="px-4 py-2 text-right font-medium">Total</th>
                      <th className="px-4 py-2 font-medium">Status</th>
                      <th className="px-4 py-2" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-100">
                    {rows.map((order) => (
                      <tr key={order.order_id} className="hover:bg-neutral-50">
                        <td className="px-4 py-2.5 font-medium">
                          #{order.order_id}
                          <div className="text-xs font-normal text-neutral-500">
                            {order.line_count} {order.line_count === 1 ? "item" : "items"} · customer{" "}
                            {order.customer_id}
                          </div>
                        </td>
                        <td className="px-4 py-2.5 text-neutral-600">{formatDateTime(order.placed_at)}</td>
                        <td className="px-4 py-2.5 text-neutral-600">
                          {order.fulfilment_method === "delivery" ? "Delivery" : "Click & Collect"}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums">{money(order.total)}</td>
                        <td className="px-4 py-2.5"><StatusBadge status={order.status} /></td>
                        <td className="px-4 py-2.5 text-right">
                          <Link href={`/admin/orders/${order.order_id}`}
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
      {!canRead && signedIn && storeId !== undefined && (
        <p className="mt-3 text-xs text-amber-700">
          You are signed in for a different store. The API will refuse this store&apos;s records.
        </p>
      )}
    </>
  );
}
