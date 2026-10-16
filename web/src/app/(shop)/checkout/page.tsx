"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import { useShop } from "@/components/shop/context";
import { CustomerGate } from "@/components/shop/customer-gate";
import { Callout, Crumbs, focusRing, PageIntro, pillLink, Price, Skeleton } from "@/components/shop/page-parts";
import { Button, Card, Empty, ErrorBox, Field, selectClass } from "@/components/ui";
import {
  type ApiError, api, call, type CustomerDetail, type OrderDetail, type ProductDetail, toApiError,
} from "@/lib/api/client";
import { fromCents, lineTotalCents } from "@/lib/cart";
import { useCart } from "@/lib/cart-context";
import {
  attemptFingerprint, type CheckoutAttempt, type CheckoutAttemptBody, clearAttempt, getOrCreateAttempt, inFlightSend,
  keepsAttempt, pendingAttempt, sendAttempt,
} from "@/lib/checkout-attempt";
import { money } from "@/lib/format";
import { SHOP_PAGES } from "@/lib/shop-pages";
import { useLoad } from "@/lib/use-load";

type Method = CheckoutAttemptBody["fulfilment_method"];
/** 409 price_changed: the total and lines at today's prices. Nothing was saved. */
type PriceChange = { total: string; lines: OrderDetail["lines"] };
/** 409 out_of_stock: the first line the fulfilling store couldn't cover. Nothing was saved. */
type Shortage = { store_id: number; product_id: number; sku: string; requested: number; available: number };
/** A failed send: the error, and the body that was sent (for "you reviewed …"). */
type Failure = { error: ApiError; sent: CheckoutAttemptBody };

// One rule keeps a lost answer from turning into a second order (BR10). While an earlier try's outcome is unknown
// (no answer, a server error, a sign-in problem: keepsAttempt in lib/checkout-attempt.ts), nothing is sent under a
// new key. The customer either sends that try again, with its own key and body, so the API returns its order if it
// went through or places it now, or checks My orders and starts a new order instead. A refusal (404, 409, 422)
// placed nothing, so its key is free and the next review gets a new one.

/** Each cart product with its current price and its stock at every store. A product the API no longer knows
 *  (404) is left out, so the page can say so; any other failure fails the load. */
async function loadProducts(ids: number[]): Promise<ProductDetail[]> {
  const found = await Promise.all(ids.map((id) =>
    call(api.GET("/api/v1/products/{product_id}", { params: { path: { product_id: id } } }))
      .catch((caught: unknown) => {
        if (toApiError(caught).status === 404) return undefined;
        throw caught;
      })));
  return found.filter((product) => product !== undefined);
}

export default function CheckoutPage() {
  return (
    <div className="space-y-8">
      <title>Checkout · TechLight</title>
      <div className="space-y-4">
        <Crumbs trail={[["Cart", SHOP_PAGES.cart.href], ["Checkout"]]} />
        <PageIntro title="Checkout">
          Choose how you get it, check what you are buying, then place the order. Payment is simulated.
        </PageIntro>
      </div>
      <CustomerGate what="check out">{(customer) => <Checkout customer={customer} />}</CustomerGate>
    </div>
  );
}

function Checkout({ customer }: { customer: CustomerDetail }) {
  const router = useRouter();
  const { stores, retailStores, store: myStore, loadError, reload, reloadCustomer } = useShop();
  const { items, ready, removeSubmitted } = useCart();
  // The earlier try in this browser that got no answer, if any (kept across tabs and reloads by
  // lib/checkout-attempt.ts). The page starts from its choices, so placing the same order again reuses its key.
  const [unanswered, setUnanswered] = useState<CheckoutAttempt | undefined>(() => {
    const attempt = pendingAttempt();
    return attempt?.customer_id === customer.customer_id ? attempt : undefined;
  });
  const [method, setMethod] = useState<Method>(unanswered?.body.fulfilment_method ?? "click_collect");
  // Where this order ships from or is collected is page state: choosing here doesn't change "My store".
  const [shipStoreId, setShipStoreId] = useState(
    unanswered?.body.fulfilment_method === "delivery" ? unanswered.body.fulfilling_store_id : undefined);
  const [collectStoreId, setCollectStoreId] = useState(
    unanswered?.body.fulfilment_method === "click_collect" ? unanswered.body.fulfilling_store_id : undefined);
  const [addressNo, setAddressNo] = useState(unanswered?.body.delivery_address_no ?? undefined);
  const [failure, setFailure] = useState<Failure>();
  // A send this page started may still be running after the customer left and came back (client-side navigation
  // unmounts the page, not the request): then the try isn't unanswered yet, it is still being placed.
  const [sending, setSending] = useState(() => unanswered !== undefined && inFlightSend(unanswered.key) !== undefined);
  const [placedId, setPlacedId] = useState<number>();

  // Wait for that earlier send, then read the stored try again: still there means it got no answer (keep it);
  // gone means it was answered, and that send has already opened its order or cleared a refused try.
  const earlierKey = unanswered?.key;
  useEffect(() => {
    const running = earlierKey === undefined ? undefined : inFlightSend(earlierKey);
    if (!running) return;
    let active = true;
    void running.then(() => {
      if (!active) return;
      const attempt = pendingAttempt();
      setUnanswered(attempt?.customer_id === customer.customer_id ? attempt : undefined);
      setSending(false);
    });
    return () => {
      active = false;
    };
  }, [earlierKey, customer.customer_id]);

  const ids = [...new Set(items.map((item) => item.product_id))].sort((a, b) => a - b);
  const products = useLoad(`checkout-products:${ids.join(",")}`, () => loadProducts(ids));
  const byId = new Map((products.data ?? []).map((product) => [product.product_id, product]));
  const lines = items.map((item) => ({ ...item, product: byId.get(item.product_id) }));
  // The total the customer reviews, in whole cents (lib/cart.ts); it is sent as expected_total.
  const totalCents = lines.reduce((sum, line) =>
    sum + (line.product ? lineTotalCents(line.product.current_price, line.quantity) : 0), 0);
  // Prices and stock for exactly this cart (useLoad keeps the last result while a reload runs).
  const loaded = products.data !== undefined && !products.loading;

  /** The lines a store can't cover in full, by the stock just loaded. Information only: the order takes the
   *  stock in the database, and says out_of_stock if it isn't there any more. */
  function shortfalls(storeId: number) {
    return lines.flatMap((line) => {
      if (!line.product) return [];
      const have = line.product.stock.find((row) => row.store_id === storeId)?.quantity ?? 0;
      return have < line.quantity ? [{ name: line.product.name, have }] : [];
    });
  }

  // Delivery ships from the warehouse unless the customer picks a store that has everything; Click & Collect is
  // at a retail store (BR06), My store unless they pick another.
  const warehouse = stores.find((s) => s.store_type === "warehouse");
  const shipFrom = stores.find((s) => s.store_id === shipStoreId) ?? warehouse;
  const shipOptions = stores
    .filter((s) => s.store_id === warehouse?.store_id || s.store_id === shipFrom?.store_id
      || (loaded && shortfalls(s.store_id).length === 0))
    .sort((a, b) => Number(b.store_type === "warehouse") - Number(a.store_type === "warehouse"));
  const collectAt = retailStores.find((s) => s.store_id === collectStoreId) ?? myStore;
  // An option's text: a store that can't fill the whole order now says so.
  const stockNote = (storeId: number) =>
    loaded && shortfalls(storeId).length > 0 ? " · not everything in stock" : "";
  const fulfilling = method === "delivery" ? shipFrom : collectAt;
  const short = fulfilling && loaded ? shortfalls(fulfilling.store_id) : [];
  const addresses = customer.addresses.filter((a) => a.is_active);
  const address = addresses.find((a) => a.address_no === addressNo) ?? addresses[0];

  // Why the order can't be placed yet, if it can't. The database checks all of this again (BR06, BR07, BR17).
  const blocker = !loaded ? (products.error ? "The current prices couldn't be loaded." : "Loading the current prices…")
    : lines.some((line) => !line.product) ? "Remove the items no longer in the catalogue from your cart."
    : lines.some((line) => !line.product?.is_active) ? "Remove the retired items from your cart."
    : !fulfilling ? "Choose a store."
    : method === "delivery" && !address ? "Add a delivery address in My account first."
    : undefined;
  const body: CheckoutAttemptBody | undefined = blocker !== undefined || !fulfilling ? undefined : {
    fulfilment_method: method,
    fulfilling_store_id: fulfilling.store_id,
    delivery_address_no: method === "delivery" ? address?.address_no ?? null : null,
    items: lines.map(({ product_id, quantity }) => ({ product_id, quantity })),
    expected_total: fromCents(totalCents),
  };
  // Today's review against the unanswered try, judged once the prices are loaded. The same review sends that try
  // again (its own key). A different one waits for the customer to choose: a price moved, a choice changed here or
  // elsewhere, or the try can't be reviewed any more.
  const retrying = unanswered !== undefined && body !== undefined && attemptFingerprint(body) === unanswered.fingerprint;
  const drifted = unanswered !== undefined && loaded && !retrying;

  /** Place the order under review: the unanswered try again if this is its review, else a new attempt. The button
   *  is disabled while the review differs from an unanswered try, so no new key goes out while that try may have
   *  placed the order. */
  function placeOrder() {
    if (unanswered && retrying) void send(unanswered);
    else if (body && !unanswered) void send(getOrCreateAttempt(customer.customer_id, body));
  }

  /** Send the unanswered try exactly as it was (its own key and body): its order if it went through, else placed
   *  now, never twice. */
  function resendEarlier() {
    if (unanswered) void send(unanswered);
  }

  /** The customer checked My orders and wants a new order instead: forget the unanswered try and its key. */
  function startOver() {
    if (unanswered) clearAttempt(unanswered.key);
    setUnanswered(undefined);
    setFailure(undefined);
  }

  async function send(attempt: CheckoutAttempt) {
    setSending(true);
    setFailure(undefined);
    try {
      // sendAttempt marks the key in flight until the answer comes, for a checkout page the customer comes back to.
      const order = await sendAttempt(attempt, () => call(api.POST("/api/v1/orders", {
        params: { header: { "Idempotency-Key": attempt.key } },
        body: attempt.body,
      })));
      // 201 is a new order, 200 the one this key placed earlier: either way it exists now. Only this try is
      // cleared: a newer one may have replaced it meanwhile.
      clearAttempt(attempt.key);
      setUnanswered(undefined);
      setPlacedId(order.order_id);
      removeSubmitted(attempt.body.items);
      router.push(`${SHOP_PAGES.orders.href}/${order.order_id}`);
    } catch (caught) {
      const error = toApiError(caught);
      setFailure({ error, sent: attempt.body });
      setSending(false);
      if (keepsAttempt(error.status)) {
        setUnanswered(attempt);                   // it may have placed the order: keep its key and body
        return;
      }
      clearAttempt(attempt.key);                  // refused: this key placed nothing, the next review gets a new one
      setUnanswered(undefined);
      if (["price_changed", "out_of_stock", "not_found"].includes(error.code) || error.code.startsWith("br07_")) {
        products.reload();                        // today's prices, stock and retired flags
      }
      if (error.code.startsWith("br17_")) reloadCustomer();   // an address retired in another tab
    }
  }

  // Changing the review makes an earlier refusal stale. An unanswered try stays: every review is compared with it
  // (retrying and drifted above), however the review changed.
  function change(update: () => void) {
    update();
    setFailure(undefined);
  }

  if (placedId !== undefined) {
    return <p role="status" className="text-[15px] text-muted">Order #{placedId} is placed. Opening it…</p>;
  }
  if (!ready) return <Skeleton className="h-48" />;
  if (items.length === 0) {
    return (
      <Card><Empty>
        Your cart is empty.{" "}
        <Link href={SHOP_PAGES.catalogue.href} className="font-bold text-brand-strong underline">Shop all products →</Link>
      </Empty></Card>
    );
  }

  const changed = failure?.error.code === "price_changed" ? failure.error.detail as PriceChange : undefined;
  const shortage = failure?.error.code === "out_of_stock" ? failure.error.detail as Shortage : undefined;

  return (
    <>
      {loadError && (
        <div className="flex flex-wrap items-center gap-3">
          <ErrorBox error={loadError} />
          <Button onClick={reload}>Try again</Button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-8">
        {/* The review can't change while an order is being placed. */}
        <fieldset disabled={sending} className="min-w-0 space-y-5">
          <Step n={1} title="How would you like it?">
            <div className="grid gap-3 sm:grid-cols-2">
              {(["click_collect", "delivery"] as const).map((option) => {
                const chosen = method === option;
                return (
                  <button key={option} type="button" aria-pressed={chosen}
                    onClick={() => change(() => setMethod(option))}
                    className={`flex items-start gap-4 rounded-card border bg-white p-4 text-left transition-colors
                      ${focusRing} ${chosen ? "border-ink ring-1 ring-ink" : "border-line hover:border-ink"}`}>
                    <span aria-hidden="true" className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[14px]
                      bg-brand-soft">
                      {option === "click_collect" ? <StoreIcon /> : <TruckIcon />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[17px] font-bold">
                        {option === "click_collect" ? "Click & Collect" : "Delivery"}
                      </span>
                      <span className="mt-0.5 block text-[14px] leading-snug text-muted">
                        {option === "click_collect"
                          ? "Collect from a retail store (never the warehouse)."
                          : "To one of your addresses, from the warehouse or a store with stock."}
                      </span>
                    </span>
                    <span aria-hidden="true" className={`mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full
                      border-2 ${chosen ? "border-ink bg-ink" : "border-line"}`}>
                      {chosen && <span className="h-2 w-2 rounded-full bg-white" />}
                    </span>
                  </button>
                );
              })}
            </div>
          </Step>

          {method === "click_collect" && (
            <Step n={2} title="Collect from">
              <Field label="Retail store" hint="Stores marked “not everything in stock” can't fill the whole order now.">
                <select className={selectClass} value={collectAt?.store_id ?? ""}
                  onChange={(event) => change(() => setCollectStoreId(Number(event.target.value)))}>
                  {!collectAt && <option value="">Loading stores…</option>}
                  {retailStores.map((s) => (
                    <option key={s.store_id} value={s.store_id}>
                      {`${s.name} — ${s.suburb} ${s.state}${stockNote(s.store_id)}`}
                    </option>
                  ))}
                </select>
              </Field>
            </Step>
          )}

          {method === "delivery" && (
            <Step n={2} title="Deliver to" actions={
              <Link href={SHOP_PAGES.account.href} className="text-[13px] font-bold text-brand-strong hover:underline">
                Manage addresses →
              </Link>}>
              <div className="space-y-5">
                {addresses.length === 0
                  ? (
                    <Callout tone="warn">
                      You have no current address.{" "}
                      <Link href={SHOP_PAGES.account.href} className="font-bold underline">Add one in My account →</Link>
                    </Callout>
                  )
                  : (
                    <fieldset>
                      <legend className="mb-2 text-[12px] font-bold tracking-[0.08em] text-muted uppercase">
                        One of your current addresses
                      </legend>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {addresses.map((a) => (
                          <label key={a.address_no} className="flex cursor-pointer items-start gap-3 rounded-card border
                            border-line bg-white p-4 text-[15px] transition-colors hover:border-ink has-checked:border-ink
                            has-checked:ring-1 has-checked:ring-ink has-focus-visible:ring-2 has-focus-visible:ring-brand">
                            <input type="radio" name="address" className="mt-1 h-4 w-4 accent-ink"
                              checked={address?.address_no === a.address_no}
                              onChange={() => change(() => setAddressNo(a.address_no))} />
                            <span>
                              <span className="block font-bold">{a.line1}</span>
                              <span className="block text-[14px] text-muted">{a.suburb} {a.state} {a.postcode}</span>
                            </span>
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  )}
                <Field label="Ship from"
                  hint="Stock is taken from here: the warehouse, unless you choose a store that has everything.">
                  <select className={selectClass} value={shipFrom?.store_id ?? ""}
                    onChange={(event) => change(() => setShipStoreId(Number(event.target.value)))}>
                    {!shipFrom && <option value="">Loading stores…</option>}
                    {shipOptions.map((s) => (
                      <option key={s.store_id} value={s.store_id}>
                        {`${s.name}${s.store_type === "warehouse" ? " (warehouse)" : ""}${stockNote(s.store_id)}`}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            </Step>
          )}

          <Step n={3} title="What you are buying"
            actions={<Link href={SHOP_PAGES.cart.href} className="text-[13px] font-bold text-brand-strong hover:underline">
              Edit cart
            </Link>}>
            {products.error && (
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <ErrorBox error={products.error} />
                <Button onClick={products.reload}>Try again</Button>
              </div>
            )}
            <ul className="divide-y divide-line">
              {lines.map((line) => (
                <li key={line.product_id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
                  <span className="min-w-0">
                    <span className="font-semibold">{line.product?.name ?? `Product #${line.product_id}`}</span>
                    <span className="block text-[13px] text-muted">
                      {line.quantity} × {line.product ? money(line.product.current_price) : "…"}
                      {line.product && !line.product.is_active && " · retired: remove it from your cart"}
                      {!line.product && loaded && " · no longer in the catalogue: remove it from your cart"}
                    </span>
                  </span>
                  <span className="font-bold tabular-nums">
                    {line.product ? money(fromCents(lineTotalCents(line.product.current_price, line.quantity))) : "…"}
                  </span>
                </li>
              ))}
            </ul>
            {fulfilling && short.length > 0 && (
              <Callout tone="warn" className="mt-4">
                {fulfilling.name} has only {short.map((s) => `${s.have} × ${s.name}`).join(", ")} right now. You can
                still try: the stock is checked again when the order is placed.
              </Callout>
            )}
          </Step>
        </fieldset>

        <aside className="lg:sticky lg:top-6 lg:self-start">
          <section aria-labelledby="pay" className="space-y-4 rounded-card border border-line bg-white p-5">
            <h2 id="pay" className="font-display text-[20px] font-bold tracking-[-0.01em]">Pay (simulated)</h2>
            <div className="flex items-baseline justify-between gap-3 border-b border-line pb-4">
              <span className="text-[15px] text-muted">Total</span>
              <Price size="xl" value={fromCents(totalCents)} />
            </div>
            <p className="text-[13px] leading-relaxed text-muted">
              The database works the total out again from today&apos;s prices when the order is placed. If it differs
              from this one, nothing is saved and you are shown the new amount.
            </p>

            {failure && changed && (
              <Callout tone="warn" role="alert" title="The price changed while you were reviewing">
                Nothing was charged. At today&apos;s prices the total is <b>{money(changed.total)}</b>, not{" "}
                {money(failure.sent.expected_total)}:
                <ul className="mt-1.5 space-y-0.5 text-[13px]">
                  {changed.lines.map((line) => (
                    <li key={line.line_no}>{line.quantity} × {line.name} at {money(line.unit_price)}</li>
                  ))}
                </ul>
                <p className="mt-1.5">The prices on this page are updated: check them, then place the order again.</p>
              </Callout>
            )}
            {shortage && (
              <Callout tone="warn" role="alert" title="Not enough stock">
                {stores.find((s) => s.store_id === shortage.store_id)?.name ?? `Store ${shortage.store_id}`} has{" "}
                {shortage.available} of {byId.get(shortage.product_id)?.name ?? shortage.sku}; you asked for{" "}
                {shortage.requested}. Nothing was charged. Choose another store, or{" "}
                <Link href={SHOP_PAGES.cart.href} className="font-bold underline">change the quantity</Link>.
              </Callout>
            )}
            {failure && !changed && !shortage && <ErrorBox error={failure.error} />}
            {retrying && !sending && (
              <p className="text-[13px] text-muted">
                An earlier try of this order got no answer, so it may have been placed. Trying again is safe: it uses
                that try&apos;s key, so you get the order if it went through, or it is placed now — never twice.
              </p>
            )}
            {drifted && !sending && (
              <Callout tone="warn" role="alert" title="An earlier try got no answer">
                It may have been placed, and your review has changed since, so a new order could buy twice. Check{" "}
                <Link href={SHOP_PAGES.orders.href} className="font-bold underline">My orders</Link>, then{" "}
                <button type="button" className="font-bold underline" disabled={sending} onClick={resendEarlier}>
                  send the earlier order again
                </button>{" "}
                (exactly as it was, with its own key: you get that order if it went through, or it is placed now —
                never twice) or, if it isn&apos;t there,{" "}
                <button type="button" className="font-bold underline" disabled={sending} onClick={startOver}>
                  start a new order
                </button>.
              </Callout>
            )}

            <Button tone="primary" className="w-full" disabled={sending || drifted || !body} onClick={placeOrder}>
              {sending ? "Placing your order…" : retrying ? "Try again" : "Place order"}
            </Button>
            {blocker && <p className="text-[13px] text-muted">{blocker}</p>}
            <Link href={SHOP_PAGES.cart.href} className={`${pillLink("sand")} w-full`}>Back to cart</Link>
          </section>
        </aside>
      </div>
    </>
  );
}

/** One numbered step of the checkout, so the order of the choices is plain. */
function Step({ n, title, actions, children }: { n: number; title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section aria-labelledby={`step-${n}`} className="rounded-card border border-line bg-white">
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5">
        <h2 id={`step-${n}`} className="flex items-center gap-3 font-display text-[19px] font-bold tracking-[-0.01em]">
          <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-full bg-ink text-[14px]
            text-white">
            {n}
          </span>
          <span><span className="sr-only">Step {n}: </span>{title}</span>
        </h2>
        {actions}
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}

function StoreIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" className="text-brand-strong">
      <path d="M4 10v10h16V10" />
      <path d="M2.5 10 5 4h14l2.5 6z" />
      <path d="M10 20v-5h4v5" />
    </svg>
  );
}

function TruckIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" className="text-brand-strong">
      <path d="M2 6h11v10H2z" />
      <path d="M13 9h4.5l3.5 3.5V16h-8" />
      <circle cx="6" cy="17.5" r="1.8" />
      <circle cx="17" cy="17.5" r="1.8" />
    </svg>
  );
}
