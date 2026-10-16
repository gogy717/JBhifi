const STEPS = ["requested", "received", "refunded"] as const;
const STEP_TEXT = { requested: "Asked for", received: "Received", refunded: "Refunded" };

/** Where the return is: asked for, received at a store, refunded. A rejection ends it at the store. */
export function ReturnProgress({ status }: { status: string }) {
  const rejected = status === "rejected";
  const reached = rejected ? 1 : STEPS.indexOf(status as (typeof STEPS)[number]);
  return (
    <ol className="grid grid-cols-3 gap-2" aria-label="Progress">
      {STEPS.map((step, index) => {
        const done = index <= reached;
        const last = rejected && index === 1;
        return (
          <li key={step} aria-current={index === reached ? "step" : undefined} className="space-y-1.5">
            <span aria-hidden="true" className={`block h-1.5 rounded-full ${
              last ? "bg-red-600" : done ? "bg-ink" : "bg-line"}`} />
            <span className={`block text-[12px] font-semibold ${done ? "text-ink" : "text-faint"}`}>
              {last ? "Rejected" : STEP_TEXT[step]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
