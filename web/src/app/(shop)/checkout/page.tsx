"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useShop } from "@/components/shop/context";
import { Button, Card, Empty, ErrorBox, selectClass } from "@/components/ui";
import { ApiError, api, call, type ProductSummary } from "@/lib/api/client";
import { fromCents, lineTotalCents } from "@/lib/cart";
import { useCart } from "@/lib/cart-context";
import { clearAttempt, getOrCreateAttempt, twoDecimals } from "@/lib/checkout-attempt";
import { money } from "@/lib/format";
import { useLoad } from "@/lib/use-load";

type Mode = "delivery" | "click_collect";

export default function CheckoutPage() {
  const router = useRouter();
  const { customer, customerLoading, store, retailStores, setStoreId, customerError } = useShop();
  const { items, ready, removeSubmitted } = useCart();
  const [mode, setMode] = useState<Mode>("click_collect");
  const [addressNo, setAddressNo] = useState<number>();
  const [storeId, setLocalStoreId] = useState<number>();
  const [error, setError] = useState<ApiError>();
  const [pending, setPending] = useState(false);

  // Current prices and stock for the lines, from the same store the customer is reviewing against.
  const pickupStore = retailStores.find((row) => row.store_id === (storeId ?? store?.store_id)) ?? store;
  const deliveryStore = store;
  const fulfillingStoreId = mode === "delivery" ? deliveryStore?.store_id : pickupStore?.store_id;
  const products = useLoad(`checkout-products:${fulfillingStoreId}`, () =>
    call(api.GET("/api/v1/products", { params: { query: { include_inactive: true, store_id: fulfillingStoreId } } })));

  const byId = new Map<number, ProductSummary>((products.data ?? []).map((row) => [row.product_id, row]));
  const lines = items.map((item) => ({ ...item, product: byId.get(item.product_id) }));
  const subtotalCents = lines.reduce((total, line) =>
    total + (line.product ? lineTotalCents(line.product.current_price, line.quantity) : 0), 0);
  const total = twoDecimals(fromCents(subtotalCents));
  const activeAddresses = (customer?.addresses ?? []).filter((address) => address.is_active);
  const chosenAddress = addressNo ?? activeAddresses[0]?.address_no;
  const readyToPlace = ready && customer !== undefined && items.length > 0
    && lines.every((line) => line.product?.is_active) && fulfillingStoreId !== undefined
    && (mode === "click_collect" || chosenAddress !== undefined)
    && (mode === "click_collect" ? pickupStore?.store_type === "retail" : true);

  async function placeOrder() {
    if (!readyToPlace || customer === undefined || fulfillingStoreId === undefined) return;
    setPending(true);
    setError(undefined);
    const body = {
      fulfilment_method: mode,
      fulfilling_store_id: fulfillingStoreId,
      delivery_address_no: mode === "delivery" ? chosenAddress ?? null : null,
      items: items.map((item) => ({ product_id: item.product_id, quantity: item.quantity })),
      expected_total: total,
    };
    // The same review keeps its key, so an uncertain outcome can be retried without a second order.
    const attempt = getOrCreateAttempt(customer.customer_id, body);
    try {
      const response = await api.POST("/api/v1/orders", {
        params: { header: { "Idempotency-Key": attempt.key } },
        body,
      });
      if (response.error || !response.data) {
        const info = (response.error as { error?: { code?: string; message?: string; detail?: unknown } } | undefined)?.error;
        throw new ApiError(response.response.status, info?.code ?? `http_${response.response.status}`,
          info?.message ?? response.response.statusText, info?.detail);
      }
      // Confirmed: take out only what was submitted, then go to the order.
      removeSubmitted(items);
      clearAttempt();
      router.push(`/orders/${response.data.order_id}`);
    } catch (failure) {
      setError(failure instanceof ApiError ? failure
        : new ApiError(0, "network_error", "The request did not get an answer. Try again — it is safe."));
      setPending(false);
    }
  }

  return (
    <div className="space-y-5">
      <title>Checkout · JB Hi-Fi</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/cart" className="hover:underline">Cart</Link> / Checkout
      </nav>
      <h1 className="text-2xl font-semibold tracking-tight">Checkout</h1>

      {customerError && <ErrorBox error={customerError} />}
      {customerLoading && <p className="text-sm text-neutral-500">Checking who is signed in…</p>}
      {!customerLoading && customer === undefined && !customerError && (
        <Card><Empty>
          Checkout needs a customer. <Link href="/" className="font-medium underline">Sign in (demo) on the
          home page</Link>, then come back.
        </Empty></Card>
      )}
      {ready && items.length === 0 && customer && (
        <Card><Empty>
          Your cart is empty. <Link href="/products" className="font-medium underline">Shop all products →</Link>
        </Empty></Card>
      )}

      {customer && items.length > 0 && (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="space-y-5">
            <Card title="How would you like it?">
              <div className="grid gap-1 p-4 sm:grid-cols-2">
                {(["click_collect", "delivery"] as const).map((option) => (
                  <button key={option} type="button" onClick={() => setMode(option)}
                    className={`rounded-lg border px-4 py-3 text-left text-sm ${
                      mode === option ? "border-neutral-900 bg-yellow-50" : "border-neutral-200 hover:bg-neutral-50"}`}>
                    <div className="font-semibold">
                      {option === "click_collect" ? "Click & Collect" : "Delivery"}
                    </div>
                    <div className="mt-0.5 text-xs text-neutral-600">
                      {option === "click_collect"
                        ? "Free to collect from a retail store (never the warehouse)."
                        : "Shipped from the warehouse or a store with stock."}
                    </div>
                  </button>
                ))}
              </div>
            </Card>

            {mode === "click_collect" && (
              <Card title="Collect from">
                <div className="space-y-3 p-4">
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">
                      Retail store
                    </span>
                    <select className={selectClass} value={pickupStore?.store_id ?? ""}
                      onChange={(event) => setLocalStoreId(Number(event.target.value))}
                      aria-label="Collect from this store">
                      {retailStores.map((row) => (
                        <option key={row.store_id} value={row.store_id}>
                          {row.name} — {row.suburb} {row.state}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="text-xs text-neutral-500">
                    You will be told when it is ready to collect from this store.
                  </p>
                </div>
              </Card>
            )}

            {mode === "delivery" && (
              <Card title="Deliver to">
                <div className="space-y-3 p-4">
                  {activeAddresses.length === 0
                    ? (
                      <p className="text-sm text-amber-800">
                        You have no current address.{" "}
                        <Link href="/account" className="font-medium underline">Add one in My account →</Link>
                      </p>
                    )
                    : (
                      <fieldset className="space-y-2">
                        <legend className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral-500">
                          One of your current addresses
                        </legend>
                        {activeAddresses.map((address) => (
                          <label key={address.address_no}
                            className="flex cursor-pointer items-start gap-3 rounded-lg border border-neutral-200 px-3 py-2 text-sm hover:bg-neutral-50">
                            <input type="radio" name="address" className="mt-1"
                              checked={chosenAddress === address.address_no}
                              onChange={() => setAddressNo(address.address_no)} />
                            <span>
                              <span className="font-medium">{address.line1}</span>
                              <span className="block text-xs text-neutral-500">
                                {address.suburb} {address.state} {address.postcode}
                              </span>
                            </span>
                          </label>
                        ))}
                      </fieldset>
                    )}
                  <label className="block">
                    <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-neutral-500">
                      Ship from
                    </span>
                    <select className={selectClass} value={deliveryStore?.store_id ?? ""}
                      onChange={(event) => setStoreId(Number(event.target.value))}
                      aria-label="Ship from this location">
                      {(products.data ?? []).length === 0 && <option value="">Loading…</option>}
                      {[...retailStores, ...(store && store.store_type === "warehouse" ? [store] : [])]
                        .filter((row, index, all) => all.findIndex((other) => other.store_id === row.store_id) === index)
                        .map((row) => <option key={row.store_id} value={row.store_id}>{row.name}</option>)}
                    </select>
                    <span className="mt-1 block text-xs text-neutral-500">
                      Stock is taken from here. The warehouse is the usual choice.
                    </span>
                  </label>
                </div>
              </Card>
            )}

            <Card title="What you are buying">
              {products.error && <ErrorBox error={products.error} className="m-4" />}
              <ul className="divide-y divide-neutral-100">
                {lines.map((line) => (
                  <li key={line.product_id} className="flex items-center justify-between gap-4 px-4 py-3 text-sm">
                    <span>
                      <span className="font-medium">{line.product?.name ?? `Product #${line.product_id}`}</span>
                      <span className="block text-xs text-neutral-500">
                        {line.quantity} × {line.product ? money(line.product.current_price) : "…"}
                        {line.product && !line.product.is_active && " · retired: remove it from the cart"}
                      </span>
                    </span>
                    <span className="tabular-nums">
                      {line.product ? money(fromCents(lineTotalCents(line.product.current_price, line.quantity))) : "…"}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          <Card title="Pay (simulated)">
            <div className="space-y-3 p-4">
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-neutral-600">Total</span>
                <span className="text-2xl font-bold tabular-nums">{money(total)}</span>
              </div>
              <p className="text-xs text-neutral-500">
                The database works the total out from the current prices at the moment the order is placed.
                If it differs from this review, nothing is saved and you are shown the new amount.
              </p>
              {error && <ErrorBox error={error} />}
              {(error?.code === "out_of_stock" || error?.code === "price_changed") && (
                <p className="text-xs text-neutral-600">
                  Nothing was charged and your cart is unchanged.{" "}
                  <Link href="/cart" className="font-medium underline">Review your cart</Link>.
                </p>
              )}
              {(error === undefined || error.code === "network_error") && (
                <Button tone="primary" className="w-full" disabled={!readyToPlace || pending}
                  onClick={placeOrder}>
                  {pending ? "Placing your order…" : error ? "Try again" : "Place order"}
                </Button>
              )}
              {error && error.code !== "network_error" && (
                <Button className="w-full" disabled={pending} onClick={placeOrder}>Try again</Button>
              )}
              {!readyToPlace && (
                <p className="text-xs text-neutral-500">
                  {mode === "delivery" && chosenAddress === undefined
                    ? "Choose an address to deliver to."
                    : "Waiting for the prices and stock to load."}
                </p>
              )}
              <p className="text-xs text-neutral-400">
                Retrying sends the same request again with the same key, so a lost reply cannot buy twice.
              </p>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
