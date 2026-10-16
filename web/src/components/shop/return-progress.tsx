const STEPS = ["requested", "received", "refunded"] as const;
const STEP_TEXT = { requested: "Asked for", received: "Received", refunded: "Refunded" };

/** Where the return is: asked for, received at a store, then refunded — or rejected, which a store does only once it
 *  has received the items, so a rejected return shows the third step as "Rejected" and no refund to come. */
export function ReturnProgress({ status }: { status: string }) {
  const rejected = status === "rejected";
  const reached = rejected ? 2 : STEPS.indexOf(status as (typeof STEPS)[number]);
  return (
    <ol className="grid grid-cols-3 gap-2" aria-label="Progress">
      {STEPS.map((step, index) => {
        const done = index <= reached;
        const refusal = rejected && index === 2;
        return (
          <li key={step} aria-current={index === reached ? "step" : undefined} className="space-y-1.5">
            <span aria-hidden="true" className={`block h-1.5 rounded-full ${
              refusal ? "bg-red-600" : done ? "bg-ink" : "bg-line"}`} />
            {/* Steps not reached yet are muted, not faint: faint is under 4.5:1 on white. */}
            <span className={`block text-[12px] ${refusal ? "font-bold text-red-700" : done ? "font-bold text-ink" : "text-muted"}`}>
              {refusal ? "Rejected" : STEP_TEXT[step]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
