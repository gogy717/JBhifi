"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { ReturnActions } from "@/components/admin/return-actions";
import { useStaff } from "@/components/admin/staff-gate";
import { ReturnStatusBadge } from "@/components/return-status";
import { Button, Card, Empty, ErrorBox, PageHeader } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

export default function ReturnPage() {
  const { id } = useParams<{ id: string }>();
  const returnId = Number(id);
  const valid = Number.isInteger(returnId) && returnId > 0;
  const me = useStaff();
  const loaded = useLoad(`return:${returnId}`, () =>
    valid ? call(api.GET("/api/v1/returns/{return_id}", { params: { path: { return_id: returnId } } }))
      : Promise.resolve(undefined));
  const detail = loaded.data?.return_id === returnId ? loaded.data : undefined;

  return (
    <>
      <title>{valid ? `Return #${returnId} · TechLight Admin` : "Return · TechLight Admin"}</title>
      <nav aria-label="Breadcrumb" className="mb-3 text-sm text-neutral-500">
        <Link href="/admin/returns" className="hover:underline">Returns</Link> / {valid ? `#${returnId}` : "…"}
      </nav>
      {!valid ? <Card><Empty>That isn&apos;t a return number.</Empty></Card>
        : loaded.error ? (
          <div className="flex flex-wrap items-center gap-3">
            <ErrorBox error={loaded.error} />
            <Button onClick={loaded.reload}>Try again</Button>
          </div>
        )
        : !detail ? <div className="h-40 animate-pulse rounded-xl bg-neutral-200" />
        : (
          <>
            <PageHeader title={`Return #${detail.return_id}`}
              description={<>
                Order #{detail.order_id} · customer #{detail.customer_id} · asked for {formatDateTime(detail.requested_at)}.
                Reason: “{detail.reason}”
              </>}
              actions={<ReturnStatusBadge status={detail.status} />} />

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
              <Card title="What comes back" actions={<span className="text-xs text-neutral-500">prices as sold (BR08)</span>}>
                <ul className="divide-y divide-neutral-100">
                  {detail.lines.map((line) => (
                    <li key={line.line_no} className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 text-sm">
                      <span>
                        <span className="font-medium">{line.name}</span>
                        <span className="block font-mono text-xs text-neutral-500">{line.sku} · order line {line.line_no}</span>
                      </span>
                      <span className="text-right tabular-nums">
                        {money(line.unit_price)} × {line.quantity}
                        <span className="block font-semibold">{money(line.line_total)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="flex items-center justify-between border-t border-neutral-200 px-4 py-3 text-sm">
                  <span className="text-neutral-600">Worth (v_return_value) — the refund is exactly this (BR14)</span>
                  <span className="text-lg font-bold tabular-nums">{money(detail.value)}</span>
                </div>
              </Card>

              <div className="space-y-4">
                <Card title="Actions" actions={<span className="text-xs text-neutral-500">R8 · T2</span>}>
                  <div className="px-4 py-3">
                    <ReturnActions detail={detail} me={me} onChanged={(changed) => loaded.setData(() => changed)}
                      onStale={loaded.reload} />
                  </div>
                </Card>
                <Card title="Where it is up to">
                  <dl className="divide-y divide-neutral-100 text-sm">
                    <Step label="Asked for" at={detail.requested_at} />
                    <Step label="Received" at={detail.received_at}
                      by={detail.received_store_name && `${detail.processed_by_name} at ${detail.received_store_name}`} />
                    <Step label={detail.status === "rejected" ? "Rejected" : "Refunded"} at={detail.resolved_at}
                      by={detail.resolved_by_name} />
                  </dl>
                  {detail.status === "rejected" && (
                    <p className="border-t border-neutral-100 px-4 py-2.5 text-sm text-red-700">Why: {detail.rejection_reason}</p>
                  )}
                  {detail.status === "refunded" && (
                    <p className="border-t border-neutral-100 px-4 py-2.5 text-sm">
                      Refund paid: <b className="tabular-nums">{detail.refunded ? money(detail.refunded) : "none (worth nothing)"}</b>
                    </p>
                  )}
                </Card>
              </div>
            </div>
          </>
        )}
    </>
  );
}

function Step({ label, at, by }: { label: string; at?: string | null; by?: string | null }) {
  return (
    <div className="flex items-baseline justify-between gap-4 px-4 py-2.5">
      <dt className="text-neutral-600">{label}</dt>
      <dd className="text-right">
        {at ? formatDateTime(at) : <span className="text-neutral-400">not yet</span>}
        {at && by && <span className="block text-xs text-neutral-500">{by}</span>}
      </dd>
    </div>
  );
}
