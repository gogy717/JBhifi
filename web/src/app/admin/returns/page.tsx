"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { CountTiles } from "@/components/admin/filters";
import { SearchIcon } from "@/components/admin/icons";
import { useStaff } from "@/components/admin/staff-gate";
import { StorePicker } from "@/components/admin/store-select";
import { Cell, Row, Table } from "@/components/admin/table";
import { RETURN_STATUS_TEXT, ReturnStatusBadge } from "@/components/return-status";
import { Button, Card, Empty, ErrorBox, inputClass, PageHeader } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

// One tile per status. Received returns wait on this store's staff (check the items, then refund or reject).
const TILES = [
  { key: "requested", hint: "Not brought in yet" },
  { key: "received", hint: "To check, then refund or reject", attention: true },
  { key: "refunded", hint: "Restocked and paid back" },
  { key: "rejected", hint: "Final, with a reason" },
];

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
  const canOpen = Number.isInteger(lookupId) && lookupId > 0;

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
        actions={<StorePicker ownStore={ownStore ? store?.name ?? me.store_name ?? "…" : undefined}
          stores={stores.data ?? []} value={storeId} onChange={setStoreId} />}
      />

      <div className="mb-5">
        <CountTiles label={`Returns at ${store?.name ?? "this store"}'s desk`} selected={status || undefined}
          onSelect={(key) => setStatus(status === key ? "" : key)}
          tiles={TILES.map((tile) => ({
            ...tile, label: RETURN_STATUS_TEXT[tile.key],
            count: desk.data?.filter((row) => row.status === tile.key).length,
          }))} />
      </div>

      <Card>
        <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line px-5 py-4">
          <form className="w-full max-w-sm" onSubmit={(event) => {
            event.preventDefault();
            if (canOpen) router.push(`/admin/returns/${lookupId}`);
          }}>
            <label htmlFor="return-lookup" className="mb-1.5 block text-xs font-semibold uppercase tracking-[0.08em]
              text-muted">
              Find return #
            </label>
            <div className="flex gap-2">
              <span className="relative min-w-0 flex-1">
                <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input id="return-lookup" className={`${inputClass} pl-10`} inputMode="numeric" placeholder="e.g. 42"
                  value={lookup} onChange={(event) => setLookup(event.target.value)}
                  aria-describedby="return-lookup-hint" />
              </span>
              <Button type="submit" disabled={!canOpen}>Open</Button>
            </div>
            <p id="return-lookup-hint" className="mt-1.5 text-xs text-muted">
              A customer can bring a return asked for on any order to any retail store.
            </p>
          </form>
          <div className="text-right text-sm text-muted">
            <div>
              {status ? <>{RETURN_STATUS_TEXT[status]} · </> : null}
              <span className="tabular-nums">{rows.length}</span> {rows.length === 1 ? "return" : "returns"}
              {status && (
                <button type="button" onClick={() => setStatus("")}
                  className="ml-2 font-semibold text-brand-strong hover:underline">Show all</button>
              )}
            </div>
            <div className="text-xs">Requested returns of this store&apos;s orders, and every return received here</div>
          </div>
        </div>
        {desk.error ? (
          <div className="flex flex-wrap items-center gap-3 p-5">
            <ErrorBox error={desk.error} />
            <Button onClick={desk.reload}>Try again</Button>
          </div>
        ) : !desk.data ? <div className="m-5 h-24 animate-pulse rounded-tile bg-sand" />
          : rows.length === 0 ? <Empty>No returns here{status && ` that are ${RETURN_STATUS_TEXT[status]?.toLowerCase()}`}.</Empty>
          : (
            <Table label={`Returns at ${store?.name ?? "this store"}`} loading={desk.loading}
              columns={["Return", "Items", { label: "Worth", align: "right" }, "Status", "Received at"]}>
              {rows.map((row) => (
                <Row key={row.return_id}>
                  <Cell className="whitespace-nowrap">
                    <Link href={`/admin/returns/${row.return_id}`}
                      className="font-semibold tabular-nums text-ink hover:text-brand-strong hover:underline">
                      #{row.return_id}
                    </Link>
                    <div className="text-xs text-muted">order #{row.order_id} · {formatDateTime(row.requested_at)}</div>
                  </Cell>
                  <Cell>
                    {row.lines.map((line) => (
                      <div key={line.line_no}><span className="tabular-nums text-muted">{line.quantity} ×</span> {line.name}</div>
                    ))}
                  </Cell>
                  <Cell numeric className="font-semibold">{money(row.value)}</Cell>
                  <Cell><ReturnStatusBadge status={row.status} /></Cell>
                  <Cell className="text-muted">{row.received_store_name ?? "—"}</Cell>
                </Row>
              ))}
            </Table>
          )}
      </Card>
    </>
  );
}
