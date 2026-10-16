"use client";

import Link from "next/link";

import { ReturnStatusBadge } from "@/components/return-status";
import { useShop } from "@/components/shop/context";
import { ErrorBox } from "@/components/ui";
import { api, call } from "@/lib/api/client";
import { formatDateTime, money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

/** The home page's "Returns" card: the signed-in customer's 3 newest returns. */
export function RecentReturns() {
  const { session } = useShop();
  const customerId = session.status === "signed-in" && session.me.kind === "customer" ? session.me.id : undefined;
  const returns = useLoad(`returns:${customerId}`, () =>
    customerId === undefined
      ? Promise.resolve([])
      : call(api.GET("/api/v1/customers/{customer_id}/returns", { params: { path: { customer_id: customerId } } })));
  const placeholder = <div aria-hidden="true" className="mt-3 h-24 animate-pulse rounded bg-neutral-100" />;
  const newest = (returns.data ?? []).slice(0, 3);

  return (
    <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-neutral-200">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-bold">Returns</h2>
        <Link href={SHOP_PAGES.returns.href} className="text-sm font-medium hover:underline">All returns →</Link>
      </div>
      {session.status === "loading" ? placeholder
        : session.status === "signed-in" && session.me.kind === "staff"
          ? <p className="mt-2 text-sm text-neutral-600">Staff accounts have no returns here.</p>
        : customerId === undefined ? <p className="mt-2 text-sm text-neutral-600">Sign in to see your returns here.</p>
        : returns.error ? <ErrorBox error={returns.error} className="mt-2" />
        : !returns.data ? placeholder
        : newest.length === 0
          ? <p className="mt-2 text-sm text-neutral-600">No returns. You can return items within 30 days of getting them.</p>
        : (
          <ul className="mt-2 divide-y divide-neutral-100">
            {newest.map((row) => (
              <li key={row.return_id}>
                <Link href={SHOP_PAGES.returns.href}
                  className="flex items-center justify-between gap-3 py-2.5 hover:bg-neutral-50">
                  <span>
                    <span className="font-medium">Return #{row.return_id}</span>
                    <span className="block text-xs text-neutral-500">{formatDateTime(row.requested_at)}</span>
                  </span>
                  <span className="flex items-center gap-3">
                    <span className="text-sm tabular-nums">{money(row.value)}</span>
                    <ReturnStatusBadge status={row.status} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
