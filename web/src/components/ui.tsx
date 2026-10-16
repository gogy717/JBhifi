"use client";

import { type ReactNode, useEffect, useId, useState } from "react";

import type { ApiError } from "@/lib/api/client";

// The redesign's language (globals.css has the tokens): controls are pills, 44px high (32px in dense admin rows);
// content sits on white cards with a `line` border and 20px corners; quiet surfaces are sand; primary actions are
// ink. Red means the brand, except in errors, which keep Tailwind's red.

// ---------------------------------------------------------------- form controls

// A textarea takes the same class for its colours and focus ring, but a pill would be the wrong shape for it.
export const inputClass =
  "h-11 w-full rounded-full border border-line bg-white px-4 text-[15px] text-ink " +
  "placeholder:text-faint focus:border-ink focus:outline-none focus:ring-2 focus:ring-brand/30 " +
  "disabled:bg-sand disabled:text-muted [&:is(textarea)]:rounded-2xl";

export const selectClass = `${inputClass} cursor-pointer pr-10`;

const buttonTones = {
  primary: "bg-ink text-white hover:bg-neutral-700 disabled:bg-neutral-300",
  secondary: "border border-line bg-white text-ink hover:bg-sand disabled:text-faint",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:bg-red-300",
  ghost: "text-muted hover:bg-sand hover:text-ink disabled:text-faint",
  // brand-strong, not brand: white text on #E64626 is 4.0:1, under AA's 4.5:1 for button-sized text.
  brand: "bg-brand-strong text-white hover:brightness-90 disabled:opacity-50",
};

export function Button({
  tone = "secondary",
  size = "md",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: keyof typeof buttonTones;
  size?: "sm" | "md";
}) {
  const sizing = size === "sm" ? "h-8 px-3.5 text-[13px] font-semibold" : "h-11 px-5 text-[15px] font-bold";
  return (
    <button
      type="button"
      className={`inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-full
        transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand
        focus-visible:ring-offset-2 disabled:cursor-not-allowed ${sizing} ${buttonTones[tone]} ${className}`}
      {...props}
    />
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  // The hint sits outside <label>, so it isn't read out as part of the control's name.
  return (
    <div>
      <label className="block">
        <span className="mb-1.5 block text-xs font-bold uppercase tracking-[0.08em] text-muted">{label}</span>
        {children}
      </label>
      {hint && <p className="mt-1.5 text-[13px] text-muted">{hint}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- display

const badgeTones = {
  neutral: "bg-sand font-semibold text-muted",
  green: "bg-emerald-50 font-semibold text-emerald-800",
  amber: "bg-amber-50 font-semibold text-warn-ink",
  red: "bg-red-50 font-semibold text-red-700",
  sale: "bg-brand-strong font-extrabold text-white",
  blue: "bg-sky-50 font-semibold text-sky-800",
};

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof badgeTones; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs
      ${badgeTones[tone]}`}>
      {children}
    </span>
  );
}

/** A small round status dot. Decorative: the words next to it say the same thing. */
export function Dot({ className }: { className: string }) {
  return <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${className}`} />;
}

export const LOW_STOCK = 3;

/** Stock at one location, for tables: a green dot when there is plenty, amber for LOW_STOCK or fewer, and the words
 *  "Out of stock" for none. The colour is never the only signal: each state also has words. */
export function StockBadge({ quantity }: { quantity: number }) {
  if (quantity === 0) {
    return (
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-sand px-2.5 py-1 text-[13px]
        font-semibold text-ink">
        <Dot className="bg-muted" />Out of stock
      </span>
    );
  }
  const low = quantity <= LOW_STOCK;
  return (
    <span className={`inline-flex min-w-14 items-center justify-center gap-1.5 rounded-full px-2.5 py-1 text-sm
      font-semibold tabular-nums ${low ? "bg-amber-50 text-warn-ink" : "bg-white text-ink ring-1 ring-line"}`}>
      <Dot className={low ? "bg-warn" : "bg-ok"} />
      <span>{quantity}</span>
      <span className="sr-only"> {low ? "low stock" : "in stock"}</span>
    </span>
  );
}

export function PageHeader({ title, description, actions }: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-[28px] font-bold leading-tight tracking-[-0.02em] text-ink md:text-[32px]">{title}</h1>
        {description && <p className="mt-2 max-w-3xl text-[15px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ title, actions, children, className = "" }: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-card border border-line bg-white ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
          <h2 className="text-base font-semibold tracking-[-0.01em] text-ink">{title}</h2>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-5 py-12 text-center text-[15px] text-muted">{children}</p>;
}

// ---------------------------------------------------------------- notices

export type Notice = { kind: "error"; error: ApiError } | { kind: "success"; text: ReactNode };

/** A page-level message: errors stay until dismissed, successes fade after a few seconds. */
export function useNotice() {
  const [notice, setNotice] = useState<Notice>();
  useEffect(() => {
    if (notice?.kind !== "success") return;
    const timer = setTimeout(() => setNotice(undefined), 4000);
    return () => clearTimeout(timer);
  }, [notice]);
  return {
    notice,
    showError: (error: ApiError) => setNotice({ kind: "error", error }),
    showSuccess: (text: ReactNode) => setNotice({ kind: "success", text }),
    clear: () => setNotice(undefined),
  };
}

export function NoticeBanner({ notice, onClose }: { notice?: Notice; onClose: () => void }) {
  if (!notice) return null;
  if (notice.kind === "success") {
    return (
      <div role="status" className="mb-5 flex items-start gap-3 rounded-card border border-emerald-200 bg-emerald-50
        px-5 py-4 text-[15px] text-emerald-950">
        <Dot className="mt-2 bg-ok" />
        <div className="min-w-0 flex-1">{notice.text}</div>
        <CloseButton onClick={onClose} />
      </div>
    );
  }
  return <ErrorBox error={notice.error} onClose={onClose} className="mb-5" />;
}

/** Shows which database rule refused a request — the code is the constraint's name. It is the demo's evidence that
 *  the rules live in the database, so it stands out: a red edge, an icon and the constraint name in a pill. */
export function ErrorBox({ error, onClose, className = "" }: {
  error: ApiError;
  onClose?: () => void;
  className?: string;
}) {
  return (
    <div role="alert" className={`flex items-start gap-3 rounded-card border border-red-200 border-l-4
      border-l-red-600 bg-red-50 px-5 py-4 text-[15px] text-red-950 ${className}`}>
      <AlertIcon />
      <div className="min-w-0 flex-1">
        <div className="font-bold">{error.isRule ? "Rejected by the database" : "Request failed"}</div>
        <div className="mt-0.5">{error.message}</div>
        <code className="mt-2 inline-block break-all rounded-full bg-white px-2.5 py-0.5 font-mono text-[13px]
          font-semibold text-red-800 ring-1 ring-red-200">
          {error.code}
        </code>
      </div>
      {onClose && <CloseButton onClick={onClose} />}
    </div>
  );
}

function AlertIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className="mt-0.5 h-5 w-5 shrink-0 text-red-600" fill="none"
      stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5.5M12 16.5v.01" />
    </svg>
  );
}

function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-label="Dismiss"
      className="-my-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xl leading-none
        opacity-60 hover:bg-black/5 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2
        focus-visible:ring-brand">
      ×
    </button>
  );
}

// ---------------------------------------------------------------- modal

export function Modal({ title, onClose, children, footer }: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const titleId = useId();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4 pt-[10vh]"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby={titleId}
        className="w-full max-w-lg rounded-panel border border-line bg-white shadow-xl">
        <header className="flex items-center justify-between gap-3 border-b border-line px-6 py-5">
          <h2 id={titleId} className="text-lg font-semibold tracking-[-0.01em] text-ink">{title}</h2>
          <CloseButton onClick={onClose} />
        </header>
        <div className="space-y-4 px-6 py-5 text-[15px]">{children}</div>
        {footer && <footer className="flex flex-wrap justify-end gap-2 border-t border-line px-6 py-4">{footer}</footer>}
      </div>
    </div>
  );
}
