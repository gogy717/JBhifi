import { ORDER_STATUS_TEXT } from "@/components/shop/order-timeline";

// The two ways through the transition table (BR09) after payment: Click & Collect and home delivery.
const PATHS: Record<string, string[]> = {
  click_collect: ["paid", "picking", "ready", "collected"],
  delivery: ["paid", "picking", "shipped", "delivered"],
};

/** Where an order is on its way to the customer: each step done, the current one, and those still to come. A
 *  cancelled order shows the steps it reached and then "Cancelled". */
export function FulfilmentPath({ method, status, reached }: {
  method: string;
  status: string;
  /** Every status the order's history records. */
  reached: string[];
}) {
  const steps = PATHS[method] ?? PATHS.click_collect;
  const cancelled = status === "cancelled";
  return (
    <ol aria-label="Steps to the customer" className="flex items-start">
      {steps.map((step, index) => {
        const current = step === status;
        const done = !current && reached.includes(step);
        const state = current ? "now" : done ? "done" : cancelled ? "not reached" : "to come";
        return (
          <li key={step} aria-current={current ? "step" : undefined} className="relative flex flex-1 flex-col items-center
            gap-2 text-center">
            {index > 0 && (
              <span aria-hidden="true" className={`absolute right-1/2 top-3.5 h-0.5 w-full
                ${done || current ? "bg-ink" : "bg-line"}`} />
            )}
            <span aria-hidden="true" className={`relative z-10 flex h-7 w-7 items-center justify-center rounded-full
              text-xs font-bold ${current ? "bg-brand-strong text-white ring-4 ring-brand-soft"
                : done ? "bg-ink text-white" : "border-2 border-line bg-white text-faint"}`}>
              {done ? "✓" : index + 1}
            </span>
            <span className={`text-xs leading-tight ${current ? "font-bold text-ink" : done ? "font-semibold text-ink"
              : "text-muted"}`}>
              {ORDER_STATUS_TEXT[step] ?? step}
              <span className="sr-only">, {state}</span>
            </span>
          </li>
        );
      })}
      {cancelled && (
        <li aria-current="step" className="relative flex flex-1 flex-col items-center gap-2 text-center">
          <span aria-hidden="true" className="absolute right-1/2 top-3.5 h-0.5 w-full bg-red-200" />
          <span aria-hidden="true" className="relative z-10 flex h-7 w-7 items-center justify-center rounded-full
            bg-red-600 text-xs font-bold text-white ring-4 ring-red-100">×</span>
          <span className="text-xs font-bold leading-tight text-red-700">
            {ORDER_STATUS_TEXT.cancelled}<span className="sr-only">, now</span>
          </span>
        </li>
      )}
    </ol>
  );
}
