"use client";

import Link from "next/link";
import { useState } from "react";

import { CountTiles, FilterPills } from "@/components/admin/filters";
import { CollectIcon, DeliveryIcon } from "@/components/admin/icons";
import { MOVES, nextMove } from "@/components/admin/order-moves";
import { useStaff } from "@/components/admin/staff-gate";
import { StorePicker } from "@/components/admin/store-select";
import { Cell, Row, Table } from "@/components/admin/table";
import { StatusBadge } from "@/components/shop/order-timeline";
import { Button, Card, Empty, ErrorBox, PageHeader } from "@/components/ui";
import { api, call, type OrderStatus } from "@/lib/api/client";
import { formatDateTime, money, timeAgo } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

// What the store still has to do: everything paid and not yet handed over or cancelled, one tile per step.
const WAITING: { status: OrderStatus; label: string; hint: string; attention?: boolean }[] = [
  { status: "paid", label: "To pick", hint: "Paid, not started", attention: true },
  { status: "picking", label: "Picking", hint: "Being picked now" },
  { status: "ready", label: "Ready to collect", hint: "Waiting for the customer" },
  { status: "shipped", label: "Shipped", hint: "On the way" },
];

const QUEUES = {
  todo: { label: "To do", statuses: WAITING.map((w) => w.status) },
  done: { label: "Delivered or collected", statuses: ["delivered", "collected"] as OrderStatus[] },
  cancelled: { label: "Cancelled", statuses: ["cancelled"] as OrderStatus[] },
  all: { label: "All", statuses: undefined },
};
type Queue = keyof typeof QUEUES;

export default function OrdersPage() {
  const me = useStaff();
  // Store staff work their own store's queue; support staff can open any store's (spec §4).
  const [storeId, setStoreId] = useState(me.store_id ?? 1);
  const [queue, setQueue] = useState<Queue>("todo");
  const [step, setStep] = useState<OrderStatus>();   // one tile of the to-do queue, or all of it

  const stores = useLoad("stores", () => call(api.GET("/api/v1/stores")));
  const listOrders = (statuses?: OrderStatus[]) => call(api.GET("/api/v1/stores/{store_id}/orders", {
    params: { path: { store_id: storeId }, query: { status: statuses } },
  }));
  // The to-do queue is always loaded: its counts head the page. The other queues are one more request.
  const todo = useLoad(`store-orders:${storeId}:todo`, () => listOrders(QUEUES.todo.statuses));
  const other = useLoad(`store-orders:${storeId}:${queue}`, () =>
    queue === "todo" ? Promise.resolve(undefined) : listOrders(QUEUES[queue].statuses));
  const shown = queue === "todo" ? todo : other;
  const rows = (shown.data ?? []).filter((row) => !step || row.status === step);
  const store = stores.data?.find((s) => s.store_id === storeId);
  // The staff member's own store is named before the store list arrives.
  const storeName = store?.name ?? (storeId === me.store_id ? me.store_name ?? undefined : undefined);

  function chooseQueue(next: Queue) {
    setQueue(next);
    setStep(undefined);
  }

  function chooseStep(next: string) {
    setQueue("todo");
    setStep(step === next ? undefined : next as OrderStatus);
  }

  return (
    <>
      <title>Orders · TechLight Admin</title>
      <PageHeader
        title="Orders"
        description={<>The store&apos;s orders, oldest first. Open one to move it along: picking, then ready for
          collection or shipped, then collected or delivered (R7). Every move is logged with who made it (R11).</>}
        actions={<StorePicker ownStore={me.staff_type === "support" ? undefined : me.store_name ?? undefined}
          stores={stores.data ?? []} value={storeId} onChange={setStoreId} />}
      />

      <div className="mb-5 space-y-3">
        <CountTiles label={`Orders waiting at ${storeName ?? "this store"}`} selected={step} onSelect={chooseStep}
          tiles={WAITING.map((w) => ({
            key: w.status, label: w.label, hint: w.hint, attention: w.attention,
            count: todo.loading ? undefined : todo.data?.filter((row) => row.status === w.status).length,
          }))} />
        {/* On the to-do queue the list below shows this error; on another queue, only the counts depend on it. */}
        {todo.error && queue !== "todo" && (
          <div className="flex flex-wrap items-center gap-3">
            <ErrorBox error={todo.error} />
            <Button onClick={todo.reload}>Try again</Button>
          </div>
        )}
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
          <FilterPills label="Show" value={queue} onChange={chooseQueue}
            options={(Object.keys(QUEUES) as Queue[]).map((key) => ({ value: key, label: QUEUES[key].label }))} />
          <h2 className="font-sans text-sm font-normal text-muted">
            {storeName} · {QUEUES[queue].label}{step && ` · ${WAITING.find((w) => w.status === step)?.label}`}
            {" "}· <span className="tabular-nums">{rows.length}</span> {rows.length === 1 ? "order" : "orders"}
          </h2>
        </div>
        {shown.error && <ErrorBox error={shown.error} className="m-5" />}
        {!shown.error && rows.length === 0 && (
          <Empty>{shown.loading ? "Loading…" : step ? "No orders at this step right now."
            : queue === "todo" ? "Nothing waiting: every order is handed over." : "No orders here."}</Empty>
        )}
        {rows.length > 0 && (
          <Table label={`Orders at ${storeName ?? "this store"}`} loading={shown.loading}
            columns={["Order", "Placed", "How", "Status", "Next", { label: "Items", align: "right" },
              { label: "Total", align: "right" }, "Last change"]}>
            {rows.map((row) => {
              const next = nextMove(row.status, row.fulfilment_method);
              return (
                <Row key={row.order_id}>
                  <Cell>
                    <Link href={`/admin/orders/${row.order_id}`}
                      className="font-semibold tabular-nums text-ink hover:text-brand-strong hover:underline">
                      #{row.order_id}
                    </Link>
                  </Cell>
                  <Cell className="whitespace-nowrap tabular-nums text-muted">{formatDateTime(row.placed_at)}</Cell>
                  <Cell className="whitespace-nowrap">
                    <span className="inline-flex items-center gap-1.5">
                      {row.fulfilment_method === "delivery"
                        ? <><DeliveryIcon className="h-4 w-4 text-muted" />Delivery</>
                        : <><CollectIcon className="h-4 w-4 text-muted" />Click &amp; Collect</>}
                    </span>
                  </Cell>
                  <Cell><StatusBadge status={row.status} /></Cell>
                  <Cell className="whitespace-nowrap">
                    {next ? (
                      <Link href={`/admin/orders/${row.order_id}`} aria-label={`${MOVES[next]} →, order #${row.order_id}`}
                        className="font-semibold text-brand-strong hover:underline">
                        {MOVES[next]} →
                      </Link>
                    ) : <span className="text-faint">—</span>}
                  </Cell>
                  <Cell numeric>{row.line_count}</Cell>
                  <Cell numeric className="font-semibold">{money(row.total)}</Cell>
                  <Cell className="whitespace-nowrap text-muted">{timeAgo(row.last_updated_at)}</Cell>
                </Row>
              );
            })}
          </Table>
        )}
      </Card>
    </>
  );
}
