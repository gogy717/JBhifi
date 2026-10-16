"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { RuleTag } from "@/components/admin/filters";
import { ReturnActions } from "@/components/admin/return-actions";
import { useStaff } from "@/components/admin/staff-gate";
import { Cell, Row, Table } from "@/components/admin/table";
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
      <nav aria-label="Breadcrumb" className="mb-3 text-sm text-muted">
        <Link href="/admin/returns" className="font-semibold text-brand-strong hover:underline">Returns</Link>
        <span aria-hidden="true"> / </span>{valid ? `#${returnId}` : "…"}
      </nav>
      {!valid ? <Card><Empty>That isn&apos;t a return number.</Empty></Card>
        : loaded.error ? (
          <div className="flex flex-wrap items-center gap-3">
            <ErrorBox error={loaded.error} />
            <Button onClick={loaded.reload}>Try again</Button>
          </div>
        )
        : !detail ? <div className="h-40 animate-pulse rounded-card bg-sand" />
        : (
          <>
            <PageHeader title={`Return #${detail.return_id}`}
              description={<>
                Order #{detail.order_id} · customer #{detail.customer_id} · asked for {formatDateTime(detail.requested_at)}.
                Reason: “{detail.reason}”
              </>}
              actions={<ReturnStatusBadge status={detail.status} />} />

            <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_24rem]">
              <Card className="self-start" title="What comes back" actions={<span className="flex items-center gap-2 text-xs
                text-muted">prices as sold <RuleTag>BR08</RuleTag></span>}>
                <Table label={`Items in return #${detail.return_id}`}
                  columns={["Product", { label: "Price", align: "right" }, { label: "Qty", align: "right" },
                    { label: "Line total", align: "right" }]}>
                  {detail.lines.map((line) => (
                    <Row key={line.line_no}>
                      <Cell>
                        <div className="font-semibold">{line.name}</div>
                        <div className="font-mono text-xs text-muted">{line.sku} · order line {line.line_no}</div>
                      </Cell>
                      <Cell numeric>{money(line.unit_price)}</Cell>
                      <Cell numeric>× {line.quantity}</Cell>
                      <Cell numeric className="font-semibold">{money(line.line_total)}</Cell>
                    </Row>
                  ))}
                </Table>
                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-canvas/60 px-5 py-4">
                  <span className="flex flex-wrap items-center gap-2 text-sm text-muted">
                    Worth (v_return_value) — the refund is exactly this <RuleTag>BR14</RuleTag>
                  </span>
                  <span className="font-display text-2xl font-bold tabular-nums">{money(detail.value)}</span>
                </div>
              </Card>

              <div className="space-y-5">
                <Card title="Actions" actions={<span className="flex gap-1"><RuleTag>R8</RuleTag><RuleTag>T2</RuleTag></span>}>
                  <div className="px-5 py-4">
                    <ReturnActions detail={detail} me={me} onChanged={(changed) => loaded.setData(() => changed)}
                      onStale={loaded.reload} />
                  </div>
                </Card>
                <Card title="Where it is up to">
                  <ol className="px-5 py-4">
                    <Step label="Asked for" at={detail.requested_at} reachedNext={!!detail.received_at} />
                    <Step label="Received" at={detail.received_at} reachedNext={!!detail.resolved_at}
                      by={detail.received_store_name && `${detail.processed_by_name} at ${detail.received_store_name}`} />
                    <Step last label={detail.status === "rejected" ? "Rejected" : "Refunded"} at={detail.resolved_at}
                      by={detail.resolved_by_name} failed={detail.status === "rejected"} />
                  </ol>
                  {detail.status === "rejected" && (
                    <p className="border-t border-line px-5 py-3 text-sm text-red-700">Why: {detail.rejection_reason}</p>
                  )}
                  {detail.status === "refunded" && (
                    <p className="border-t border-line px-5 py-3 text-sm">
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

/** One step of a return, on a vertical line: the dot fills once the step has happened, the line below it once the
 *  next one has. */
function Step({ label, at, by, reachedNext = false, last = false, failed = false }: {
  label: string;
  at?: string | null;
  by?: string | null;
  reachedNext?: boolean;
  last?: boolean;
  failed?: boolean;
}) {
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      {!last && (
        <span aria-hidden="true" className={`absolute left-[7px] top-5 h-full w-0.5 ${reachedNext ? "bg-ink" : "bg-line"}`} />
      )}
      <span aria-hidden="true" className={`relative z-10 mt-1 h-4 w-4 shrink-0 rounded-full ${!at
        ? "border-2 border-line bg-white" : failed ? "bg-red-600" : "bg-ink"}`} />
      <div className="flex min-w-0 flex-1 flex-wrap items-baseline justify-between gap-x-4 text-sm">
        <span className={at ? "font-semibold" : "text-muted"}>{label}</span>
        <span className="text-right">
          {at ? <span className="tabular-nums">{formatDateTime(at)}</span> : <span className="text-faint">not yet</span>}
          {at && by && <span className="block text-xs text-muted">{by}</span>}
        </span>
      </div>
    </li>
  );
}
