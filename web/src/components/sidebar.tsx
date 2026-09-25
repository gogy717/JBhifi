"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useLoad } from "@/lib/use-load";

const LINKS = [
  { href: "/inventory", label: "Inventory", hint: "Stock per store, ± adjustments" },
  { href: "/products", label: "Products", hint: "Catalogue, prices, specs" },
  { href: "/promotions", label: "Promotions", hint: "Sale prices over a period" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex w-full shrink-0 flex-col bg-neutral-900 text-neutral-300 md:min-h-screen md:w-60">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <span className="flex h-8 w-8 items-center justify-center rounded bg-yellow-300 text-sm font-black text-neutral-900">
          JB
        </span>
        <div>
          <div className="text-sm font-semibold text-white">Store Admin</div>
          <div className="text-xs text-neutral-400">Phase 1 prototype</div>
        </div>
      </div>
      <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:pb-0">
        {LINKS.map((link) => {
          const active = pathname.startsWith(link.href);
          return (
            <Link key={link.href} href={link.href}
              className={`rounded-md px-3 py-2 transition-colors ${
                active ? "bg-neutral-800 text-white" : "hover:bg-neutral-800/60 hover:text-white"}`}>
              <div className="text-sm font-medium">{link.label}</div>
              <div className="hidden text-xs text-neutral-400 md:block">{link.hint}</div>
            </Link>
          );
        })}
      </nav>
      <ApiStatus />
    </aside>
  );
}

function ApiStatus() {
  const health = useLoad("health", async () => {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error(response.statusText);
    return (await response.json()) as { status: string; db: string };
  });
  const ok = health.data !== undefined && !health.error;
  return (
    <div className="mt-auto hidden items-center gap-2 px-5 py-4 text-xs text-neutral-400 md:flex">
      <span className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-400" : health.loading ? "bg-neutral-500" : "bg-red-500"}`} />
      {ok ? <>API connected · db <code className="text-neutral-200">{health.data?.db}</code></>
        : health.loading ? "Checking API…" : "API unreachable"}
      {!ok && !health.loading && (
        <button type="button" onClick={health.reload} className="underline hover:text-white">retry</button>
      )}
    </div>
  );
}
