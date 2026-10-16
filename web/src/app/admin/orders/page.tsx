"use client";

import Link from "next/link";
import { useState } from "react";

import { useStaff } from "@/components/admin/staff-gate";
import { StoreSelect } from "@/components/admin/store-select";
import { ORDER_STATUS_TEXT, StatusBadge } from "@/components/shop/order-timeline";
import { Card, Empty, ErrorBox, Field, PageHeader, selectClass } from "@/components/ui";
import { api, call, type OrderStatus } from "@/lib/api/client";
import { formatDateTime, money, timeAgo } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

// What the store still has to do: everything paid and not yet handed over or cancelled.
const FILTERS: Record<string, { label: string; statuses?: OrderStatus[] }> = {
  todo: { label: "To do", statuses: ["paid", "picking", "ready", "shipped"] },
  paid: { label: ORDER_STATUS_TEXT.paid, statuses: ["paid"] },
  picking: { label: ORDER_STATUS_TEXT.picking, statuses: ["picking"] },
  ready: { label: ORDER_STATUS_TEXT.ready, statuses: ["ready"] },
  shipped: { label: ORDER_STATUS_TEXT.shipped, statuses: ["shipped"] },
  done: { label: "Delivered or collected", statuses: ["delivered", "collected"] },
  cancelled: { label: ORDER_STATUS_TEXT.cancelled, statuses: ["cancelled"] },
  all: { label: "All" },
};

export default function OrdersPage() {
  const me = useStaff();
  // Store staff work their own store's queue; support staff can open any store's (spec §4).
  const [storeId, setStoreId] = useState(me.store_id ?? 1);
  const [filter, setFilter] = useState("todo");
  const statuses = FILTERS[filter].statuses;

  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));
  const orders = useLoad(`store-orders:${storeId}:${filter}`, () =>
    call(api.GET("/api/v1/stores/{store_id}/orders", {
      params: { path: { store_id: storeId }, query: { status: statuses } },
    })));
  const store = stores.data?.find((s) => s.store_id === storeId);
  const rows = orders.data ?? [];

  return (
    <>
      <title>Orders · TechLight Admin</title>
      <PageHeader
        title="Orders"
        description={<>The store&apos;s orders, oldest first. Open one to move it along: picking, then ready for
          collection or shipped, then collected or delivered (R7). Every move is logged with who made it (R11).</>}
      />

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-[16rem_14rem]">
        <Field label="Store">
          {me.staff_type === "support"
            ? <StoreSelect stores={stores.data ?? []} value={storeId} onChange={setStoreId} />
            : <p className="flex h-9 items-center text-sm font-medium">{me.store_name}</p>}
        </Field>
        <Field label="Show">
          <select className={selectClass} value={filter} onChange={(e) => setFilter(e.target.value)}>
            {Object.entries(FILTERS).map(([key, { label }]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </Field>
      </div>

      <Card title={store?.name ?? "Orders"} actions={<span className="text-xs text-neutral-500">{rows.length} orders</span>}>
        {orders.error && <ErrorBox error={orders.error} className="m-4" />}
        {!orders.error && rows.length === 0 && <Empty>{orders.loading ? "Loading…" : "No orders here."}</Empty>}
        {rows.length > 0 && (
          <div className={`overflow-x-auto ${orders.loading ? "opacity-60" : ""}`}>
            <table className="w-full text-sm">
              <thead className="bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Order</th>
                  <th className="px-4 py-2 font-medium">Placed</th>
                  <th className="px-4 py-2 font-medium">How</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 text-right font-medium">Items</th>
                  <th className="px-4 py-2 text-right font-medium">Total</th>
                  <th className="px-4 py-2 font-medium">Last change</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {rows.map((row) => (
                  <tr key={row.order_id} className="hover:bg-neutral-50">
                    <td className="px-4 py-2.5">
                      <Link href={`/admin/orders/${row.order_id}`} className="font-medium hover:underline">
                        #{row.order_id}
                      </Link>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2.5 tabular-nums text-neutral-600">
                      {formatDateTime(row.placed_at)}
                    </td>
                    <td className="px-4 py-2.5 text-neutral-600">
                      {row.fulfilment_method === "delivery" ? "Delivery" : "Click & Collect"}
                    </td>
                    <td className="px-4 py-2.5"><StatusBadge status={row.status} /></td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{row.line_count}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{money(row.total)}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-neutral-500">{timeAgo(row.last_updated_at)}</td>
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
