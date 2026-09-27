"use client";

import { type ReactNode, useEffect, useId, useRef, useState } from "react";

import type { ApiError } from "@/lib/api/client";

// ---------------------------------------------------------------- form controls

export const inputClass =
  "h-9 w-full rounded-md border border-neutral-300 bg-white px-3 text-sm text-neutral-900 " +
  "placeholder:text-neutral-400 focus:border-neutral-900 focus:outline-none focus:ring-2 focus:ring-yellow-300 " +
  "disabled:bg-neutral-100 disabled:text-neutral-500";

export const selectClass = `${inputClass} pr-8`;

const buttonTones = {
  primary: "bg-neutral-900 text-white hover:bg-neutral-700 disabled:bg-neutral-400",
  secondary: "border border-neutral-300 bg-white text-neutral-800 hover:bg-neutral-50 disabled:text-neutral-400",
  danger: "bg-red-600 text-white hover:bg-red-500 disabled:bg-red-300",
  ghost: "text-neutral-700 hover:bg-neutral-100 disabled:text-neutral-300",
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
  const sizing = size === "sm" ? "h-7 px-2 text-xs" : "h-9 px-3.5 text-sm";
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors
        disabled:cursor-not-allowed ${sizing} ${buttonTones[tone]} ${className}`}
      {...props}
    />
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  // The hint sits outside <label>, so it isn't read out as part of the control's name.
  return (
    <div>
      <label className="block">
        <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">{label}</span>
        {children}
      </label>
      {hint && <p className="mt-1 text-xs text-neutral-500">{hint}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- display

const badgeTones = {
  neutral: "bg-neutral-100 text-neutral-700",
  green: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  amber: "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-1 ring-red-200",
  sale: "bg-yellow-300 text-neutral-900",
  blue: "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
};

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof badgeTones; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${badgeTones[tone]}`}>
      {children}
    </span>
  );
}

export const LOW_STOCK = 3;

export function StockBadge({ quantity }: { quantity: number }) {
  const tone = quantity === 0 ? "red" : quantity <= LOW_STOCK ? "amber" : "green";
  return (
    <span className={`inline-flex min-w-10 justify-center rounded-md px-2 py-1 text-sm font-semibold tabular-nums
      ${badgeTones[tone]}`}>
      {quantity}
    </span>
  );
}

export function PageHeader({ title, description, actions }: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-neutral-900">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-neutral-600">{description}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
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
    <section className={`rounded-xl border border-neutral-200 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-neutral-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-900">{title}</h2>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-4 py-10 text-center text-sm text-neutral-500">{children}</p>;
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
      <div role="status" className="mb-4 flex items-start justify-between gap-4 rounded-lg border border-emerald-200
        bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
        <div>{notice.text}</div>
        <CloseButton onClick={onClose} />
      </div>
    );
  }
  return <ErrorBox error={notice.error} onClose={onClose} className="mb-4" />;
}

/** Shows which database rule refused a request — the code is the constraint's name. */
export function ErrorBox({ error, onClose, onRetry, className = "" }: {
  error: ApiError;
  onClose?: () => void;
  /** Offered when the screen cannot work without the failed data (a store or brand list, say). */
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div role="alert" className={`flex items-start justify-between gap-4 rounded-lg border border-red-200 bg-red-50
      px-4 py-3 text-sm text-red-900 ${className}`}>
      <div>
        <div className="font-semibold">{error.isRule ? "Rejected by the database" : "Request failed"}</div>
        <div className="mt-0.5">{error.message}</div>
        <code className="mt-1.5 inline-block rounded bg-red-100 px-1.5 py-0.5 font-mono text-xs text-red-800">
          {error.code}
        </code>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {onRetry && <Button size="sm" onClick={onRetry}>Retry</Button>}
        {onClose && <CloseButton onClick={onClose} />}
      </div>
    </div>
  );
}

function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-label="Dismiss"
      className="rounded px-1.5 text-lg leading-none opacity-60 hover:opacity-100">
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
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // A dialog the keyboard can actually use: it has a name (aria-labelledby), focus starts inside it,
    // Tab cycles within it instead of wandering into the page behind, Escape closes it, and closing
    // puts focus back on whatever opened it. The page behind cannot be scrolled or clicked meanwhile.
    const opener = document.activeElement;
    const focusable = () => Array.from(dialog.current?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) ?? []);

    // A control that asked for focus itself (autoFocus) keeps it; otherwise focus the first control.
    if (!dialog.current?.contains(document.activeElement)) {
      (focusable()[0] ?? dialog.current)?.focus();
    }

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (items.length === 0) {
        event.preventDefault();
        dialog.current?.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const inside = dialog.current?.contains(document.activeElement) ?? false;
      if (event.shiftKey && (!inside || document.activeElement === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || document.activeElement === last)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = previousOverflow;
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-neutral-900/40 p-4 pt-[10vh]"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className="w-full max-w-lg rounded-xl bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-neutral-200 px-5 py-4">
          <h2 id={titleId} className="text-base font-semibold text-neutral-900">{title}</h2>
          <CloseButton onClick={onClose} />
        </header>
        <div className="space-y-4 px-5 py-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-neutral-200 px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}
