"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { ReturnActions } from "@/components/admin/return-actions";
import { RETURN_STATUS_TEXT } from "@/components/shop/order-timeline";
import { Button, Card, Empty, ErrorBox, PageHeader } from "@/components/ui";
import { api, call, type ReturnStatusEntry } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function AdminReturnPage() {
  const params = useParams<{ id: string }>();
  const returnKey = `admin-return:${params.id}`;
  const detail = useLoad(returnKey, () =>
    call(api.GET("/api/v1/returns/{return_id}", { params: { path: { return_id: Number(params.id) } } })));
  const row = detail.data;

  return (
    <>
      <title>{row ? `Return #${row.return_id} · JB Admin` : "Return · JB Admin"}</title>
      <nav aria-label="Breadcrumb" className="mb-3 text-sm text-neutral-500">
        <Link href="/admin/returns" className="hover:underline">Returns desk</Link> /{" "}
        {row ? `#${row.return_id}` : "…"}
      </nav>

      {detail.error && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <ErrorBox error={detail.error} />
          <Button onClick={detail.reload}>Try again</Button>
        </div>
      )}
      {!detail.error && !row && <div className="h-40 animate-pulse rounded-xl bg-neutral-200" />}

      {row && (
        <>
          <PageHeader
            title={`Return #${row.return_id}`}
            description={<>
              Order #{row.order_id} · requested {formatDateTime(row.requested_at)} ·{" "}
              {row.receiving_store
                ? `received at ${row.receiving_store.name}`
                : "not received yet"}
            </>}
          />

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <div className="space-y-4">
              <Card title="Next step">
                <div className="p-4">
                  <ReturnActions detail={row}
                    onChanged={(updated) => detail.setData(returnKey, () => updated)} />
                </div>
              </Card>

              <Card title="What came back" actions={
                <span className="text-xs text-neutral-500">
                  refund preview {money(String(row.refund_preview))}
                </span>}>
                <ul className="divide-y divide-neutral-100">
                  {row.lines.map((line) => (
                    <li key={line.line_no} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                      <div>
                        <div className="font-medium">{line.name}</div>
                        <div className="font-mono text-xs text-neutral-500">
                          {line.sku} · bought at {money(line.unit_price)}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-lg font-semibold tabular-nums">× {line.quantity}</div>
                        <div className="text-xs text-neutral-500 tabular-nums">{money(line.line_total)}</div>
                      </div>
                    </li>
                  ))}
                </ul>
                <div className="flex items-center justify-between border-t border-neutral-200 px-4 py-3">
                  <span className="text-sm text-neutral-600">Refund if processed</span>
                  <span className="text-lg font-bold tabular-nums">{money(String(row.refund_preview))}</span>
                </div>
                <p className="border-t border-neutral-200 px-4 py-3 text-xs text-neutral-500">
                  Refunds use the price each item was sold at (BR08), never today&apos;s price. Restocking puts
                  the quantities back at the store that received them.
                </p>
              </Card>

              <Card title="Why the customer asked">
                <p className="px-4 py-3 text-sm text-neutral-800">“{row.reason}”</p>
              </Card>
            </div>

            <div className="space-y-4">
              <Card title="Timeline">
                {row.history.length === 0
                  ? <Empty>No history.</Empty>
                  : (
                    <ol className="divide-y divide-neutral-100">
                      {row.history.map((change: ReturnStatusEntry) => (
                        <li key={change.seq} className="px-4 py-2.5 text-sm">
                          <div className="flex items-baseline justify-between gap-3">
                            <span className="font-medium">
                              {RETURN_STATUS_TEXT[change.to_status] ?? change.to_status}
                            </span>
                            <span className="text-xs tabular-nums text-neutral-500">
                              {formatDateTime(change.changed_at)}
                            </span>
                          </div>
                          <div className="text-xs text-neutral-500">
                            {change.from_status
                              ? `from ${RETURN_STATUS_TEXT[change.from_status] ?? change.from_status}`
                              : "request created"}
                            {change.changed_by_name
                              ? ` · by ${change.changed_by_name}`
                              : " · by the customer"}
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}
              </Card>

              <Card title="Money">
                <dl className="divide-y divide-neutral-100 text-sm">
                  <div className="flex justify-between gap-4 px-4 py-2.5">
                    <dt className="text-neutral-500">Refunded</dt>
                    <dd className="font-semibold tabular-nums">
                      {row.refund_amount ? money(row.refund_amount) : "nothing yet"}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-4 px-4 py-2.5">
                    <dt className="text-neutral-500">Receiving store</dt>
                    <dd>{row.receiving_store?.name ?? "—"}</dd>
                  </div>
                </dl>
                <div className="border-t border-neutral-200 px-4 py-3">
                  <Link href={`/admin/orders/${row.order_id}`} className="text-sm font-medium hover:underline">
                    Open order #{row.order_id} →
                  </Link>
                </div>
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
}
