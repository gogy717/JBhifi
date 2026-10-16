import Link from "next/link";
import type { ReactNode } from "react";

import { money } from "@/lib/format";

// The storefront pages' own building blocks, in the homepage redesign's language (tokens in app/globals.css):
// Sora headings and prices, pill-shaped controls, white cards on the canvas, one accent. The shared controls
// (Button, Card, Badge, Field, ErrorBox …) stay in components/ui.tsx.

/** The brand focus ring, for links and buttons styled here. */
export const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2";

const pillTones = {
  ink: "bg-ink text-white hover:bg-ink/85",
  outline: "border border-line bg-white text-ink hover:border-ink",
  sand: "bg-sand text-ink hover:bg-line",
};

/** A link that looks like a button: 44px (md) or 32px (sm), the same heights as Button. */
export function pillLink(tone: keyof typeof pillTones = "outline", size: "sm" | "md" = "md"): string {
  const sizing = size === "sm" ? "h-8 px-3.5 text-[13px]" : "h-11 px-5 text-[15px]";
  return `inline-flex items-center justify-center gap-2 rounded-full font-bold whitespace-nowrap transition-colors
    ${sizing} ${pillTones[tone]} ${focusRing}`;
}

/** Where the page sits: each step a link, the last one the current page. */
export function Crumbs({ trail }: { trail: [label: ReactNode, href?: string][] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
        {trail.map(([label, href], index) => {
          const last = index === trail.length - 1;
          return (
            <li key={index} className="flex min-w-0 items-center gap-2">
              {href && !last
                ? <Link href={href} className={`rounded hover:text-brand-strong ${focusRing}`}>{label}</Link>
                : <span aria-current={last ? "page" : undefined} className="truncate font-medium text-ink">{label}</span>}
              {!last && <span aria-hidden="true" className="text-faint">/</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** A small capitalised label above a heading or a value. */
export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span className={`block text-[12px] font-bold tracking-[0.08em] text-muted uppercase ${className}`}>
      {children}
    </span>
  );
}

/** The page's heading block: an optional eyebrow, the h1, a sentence about the page, and actions on the right. */
export function PageIntro({ eyebrow, title, children, actions }: {
  eyebrow?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0 space-y-2">
        {eyebrow && <Eyebrow>{eyebrow}</Eyebrow>}
        <h1 className="font-display text-[32px] leading-[1.1] font-bold tracking-[-0.025em] sm:text-[40px]">{title}</h1>
        {children && <div className="max-w-2xl text-[15px] leading-relaxed text-muted">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

/** A section heading inside a page (Sora, like the homepage's "Current deals"). */
export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <h2 className="font-display text-[22px] font-bold tracking-[-0.02em] sm:text-[24px]">{children}</h2>
      {aside}
    </div>
  );
}

const calloutTones = {
  warn: "border-warn/30 bg-warn/10 text-warn-ink",
  ok: "border-ok/25 bg-ok/10 text-ink",
  brand: "border-brand/15 bg-brand-soft text-ink",
  quiet: "border-line bg-sand text-ink",
};

/** A soft box for a note the customer should read: a warning, a confirmation, or a tip. Errors use ErrorBox. */
export function Callout({ tone = "quiet", title, role, children, className = "" }: {
  tone?: keyof typeof calloutTones;
  title?: ReactNode;
  role?: "status" | "alert";
  children: ReactNode;
  className?: string;
}) {
  return (
    <div role={role} className={`rounded-tile border px-4 py-3 text-sm leading-relaxed ${calloutTones[tone]} ${className}`}>
      {title && <div className="font-bold">{title}</div>}
      <div className={title ? "mt-0.5" : ""}>{children}</div>
    </div>
  );
}

const priceSizes = { md: "text-[20px]", lg: "text-[24px]", xl: "text-[36px] sm:text-[40px]" };

/** A price in Sora, with the price before the promotion struck through when there is one. */
export function Price({ value, was, size = "lg" }: { value: string; was?: string; size?: keyof typeof priceSizes }) {
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-2">
      <span className={`font-display font-extrabold tracking-[-0.02em] tabular-nums ${priceSizes[size]}`}>
        {money(value)}
      </span>
      {was && <s className="text-sm text-muted"><span className="sr-only">was </span>{money(was)}</s>}
    </span>
  );
}

/** One row of label and value, for the detail cards (payment, specifications, account details). */
export function DetailRow({ label, children, strong = false }: { label: ReactNode; children: ReactNode; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 px-5 py-3 text-[15px]">
      <dt className="text-muted">{label}</dt>
      <dd className={`text-right ${strong ? "font-bold" : ""}`}>{children}</dd>
    </div>
  );
}

/** A grey block standing in for content that is still loading. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded-card bg-sand ${className}`} />;
}

/** − n + in a pill. Never below min: only a separate "Remove" takes a cart line out. */
export function QuantityStepper({ value, min = 1, max, onChange, label }: {
  value: number;
  min?: number;
  max: number;
  onChange: (value: number) => void;
  /** What is being counted, for screen readers, e.g. "Quantity of AirPods 4". */
  label: string;
}) {
  const step = `flex h-full w-10 items-center justify-center rounded-full text-lg leading-none transition-colors
    hover:bg-sand disabled:cursor-not-allowed disabled:text-faint disabled:hover:bg-transparent ${focusRing}`;
  return (
    <div role="group" aria-label={label}
      className="inline-flex h-11 items-center rounded-full border border-line bg-white p-0.5">
      <button type="button" className={step} aria-label="One fewer" disabled={value <= min}
        onClick={() => onChange(value - 1)}>−</button>
      <span className="w-8 text-center text-[15px] font-bold tabular-nums">{value}</span>
      <button type="button" className={step} aria-label="One more" disabled={value >= max}
        onClick={() => onChange(value + 1)}>+</button>
    </div>
  );
}
