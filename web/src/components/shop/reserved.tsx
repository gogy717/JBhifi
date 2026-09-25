import Link from "next/link";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui";
import { REQUIREMENTS, RULES, SHOP_PAGES, type ShopPageId, TRANSACTIONS } from "@/lib/shop-pages";

/** A page that is planned but not built yet: what it will do, what it covers, and the API it needs. */
export function ReservedPage({ id, children }: { id: ShopPageId; children?: ReactNode }) {
  const page = SHOP_PAGES[id];
  const transaction = "transaction" in page ? page.transaction : undefined;
  return (
    <div className="mx-auto max-w-4xl">
      <title>{`${page.title} · JB Hi-Fi`}</title>
      <nav aria-label="Breadcrumb" className="mb-3 text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> / {page.title}
      </nav>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{page.title}</h1>
        <Badge tone="amber">Reserved — not built yet</Badge>
      </div>
      <p className="mb-6 max-w-2xl text-neutral-600">{page.summary}</p>

      {children && (
        <div className="mb-6 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900">{children}</div>
      )}

      <div className="grid grid-cols-1 gap-4 rounded-xl border-2 border-dashed border-neutral-300 p-4 md:grid-cols-2">
        <Section title="What it will do">
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-neutral-700">
            {page.features.map((feature) => <li key={feature}>{feature}</li>)}
          </ul>
        </Section>

        <Section title="What it covers">
          <dl className="space-y-1.5 text-sm">
            {page.requirements.map((r) => <Covered key={r} code={r} text={REQUIREMENTS[r]} />)}
            {page.rules.map((r) => <Covered key={r} code={r} text={RULES[r]} />)}
            {transaction && <Covered code={transaction} text={TRANSACTIONS[transaction]} />}
          </dl>
        </Section>

        <Section title="API it needs">
          <ul className="space-y-1.5 text-sm">
            {page.api.map((e) => (
              <li key={e.method + e.path} className="flex flex-wrap items-baseline gap-2">
                <code className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs font-semibold">{e.method}</code>
                <code className="min-w-0 text-xs break-all text-neutral-800">{e.path}</code>
                <Badge tone={e.exists ? "green" : "neutral"}>{e.exists ? "exists" : "to build"}</Badge>
              </li>
            ))}
          </ul>
        </Section>

        <Section title="Owner">
          <p className="text-sm text-neutral-700">Slice {page.slice} (plan §10)</p>
          <p className="mt-2 text-xs text-neutral-500">
            Page file: <code className="break-all">web/src/app/(shop){page.href}/page.tsx</code>
          </p>
        </Section>
      </div>

      <Link href="/" className="mt-6 inline-block text-sm font-medium text-neutral-700 hover:underline">
        ← Back to the home page
      </Link>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg bg-white p-4 shadow-sm ring-1 ring-neutral-200">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h2>
      {children}
    </section>
  );
}

function Covered({ code, text }: { code: string; text: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-12 shrink-0 font-mono text-xs font-semibold leading-5 text-neutral-900">{code}</dt>
      <dd className="text-neutral-700">{text}</dd>
    </div>
  );
}
