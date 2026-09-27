"use client";

import Link from "next/link";
import { useState } from "react";

import { AddressForm } from "@/components/shop/address-form";
import { useShop } from "@/components/shop/context";
import { Badge, Button, Card, Empty, ErrorBox, Modal } from "@/components/ui";
import { ApiError, api, call, type Address } from "@/lib/api/client";
import { formatDate } from "@/lib/format";

export default function AccountPage() {
  const { customer, customerLoading, customerError, reload } = useShop();
  const [adding, setAdding] = useState(false);
  const [retiring, setRetiring] = useState<Address>();
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<ApiError>();
  const [pending, setPending] = useState(false);

  async function retire(address: Address) {
    if (!customer) return;
    setPending(true);
    setError(undefined);
    try {
      await call(api.PATCH("/api/v1/customers/{customer_id}/addresses/{address_no}", {
        params: { path: { customer_id: customer.customer_id, address_no: address.address_no } },
        body: { is_active: false },
      }));
      setRetiring(undefined);
      setNotice(`Address ${address.address_no} (${address.line1}) is retired. Orders already placed keep it.`);
      reload();
    } catch (failure) {
      setError(failure instanceof ApiError ? failure
        : new ApiError(0, "network_error", "The request did not get an answer."));
    } finally {
      setPending(false);
    }
  }

  const addresses = customer?.addresses ?? [];
  const current = addresses.filter((address) => address.is_active);
  const past = addresses.filter((address) => !address.is_active);

  return (
    <div className="space-y-5">
      <title>My account · JB Hi-Fi</title>
      <nav aria-label="Breadcrumb" className="text-sm text-neutral-500">
        <Link href="/" className="hover:underline">Home</Link> / My account
      </nav>

      <h1 className="text-2xl font-semibold tracking-tight">My account</h1>

      {customerError && <ErrorBox error={customerError} />}
      {customerLoading && <p className="text-sm text-neutral-500">Checking who is signed in…</p>}
      {!customerLoading && !customer && !customerError && (
        <Card><Empty>
          Sign in (demo) on the <Link href="/" className="font-medium underline">home page</Link> to see your
          details.
        </Empty></Card>
      )}

      {customer && (
        <>
          {notice && (
            <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm
              text-emerald-900">
              {notice}
              <button type="button" className="ml-3 underline" onClick={() => setNotice(undefined)}>dismiss</button>
            </p>
          )}
          {error && !retiring && <ErrorBox error={error} />}

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
            <Card title="Your details">
              <dl className="divide-y divide-neutral-100 text-sm">
                <div className="flex justify-between gap-4 px-4 py-2.5">
                  <dt className="text-neutral-500">Name</dt>
                  <dd className="font-medium">{customer.full_name}</dd>
                </div>
                <div className="flex justify-between gap-4 px-4 py-2.5">
                  <dt className="text-neutral-500">Email</dt>
                  <dd className="font-mono text-xs">{customer.email}</dd>
                </div>
                <div className="flex justify-between gap-4 px-4 py-2.5">
                  <dt className="text-neutral-500">Phone</dt>
                  <dd>{customer.phone ?? "—"}</dd>
                </div>
                <div className="flex justify-between gap-4 px-4 py-2.5">
                  <dt className="text-neutral-500">Customer since</dt>
                  <dd>{formatDate(customer.created_at)}</dd>
                </div>
                <div className="flex justify-between gap-4 px-4 py-2.5">
                  <dt className="text-neutral-500">Customer #</dt>
                  <dd className="tabular-nums">{customer.customer_id}</dd>
                </div>
              </dl>
              <p className="border-t border-neutral-200 px-4 py-3 text-xs text-neutral-500">
                The email is unique and stored in lower case (BR01). Demo sign-in stands in for a login.
              </p>
            </Card>

            <div className="space-y-5">
              <Card title="Current delivery addresses"
                actions={<Button size="sm" onClick={() => setAdding(true)}>Add address</Button>}>
                {current.length === 0
                  ? <Empty>No current address. Add one before ordering delivery.</Empty>
                  : (
                    <ul className="divide-y divide-neutral-100">
                      {current.map((address) => (
                        <li key={address.address_no}
                          className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                          <div>
                            <div className="font-medium">{address.line1}</div>
                            <div className="text-xs text-neutral-500">
                              {address.suburb} {address.state} {address.postcode} · #{address.address_no}
                            </div>
                          </div>
                          <Button size="sm" onClick={() => setRetiring(address)}>Retire…</Button>
                        </li>
                      ))}
                    </ul>
                  )}
                <p className="border-t border-neutral-200 px-4 py-3 text-xs text-neutral-500">
                  Retiring replaces an address without rewriting it: orders already placed keep the address
                  they were placed with (BR16).
                </p>
              </Card>

              {past.length > 0 && (
                <Card title="Past addresses">
                  <ul className="divide-y divide-neutral-100">
                    {past.map((address) => (
                      <li key={address.address_no}
                        className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                        <div>
                          <div className="text-neutral-700">{address.line1}</div>
                          <div className="text-xs text-neutral-500">
                            {address.suburb} {address.state} {address.postcode} · #{address.address_no}
                          </div>
                        </div>
                        <Badge>retired</Badge>
                      </li>
                    ))}
                  </ul>
                  <p className="border-t border-neutral-200 px-4 py-3 text-xs text-neutral-500">
                    An address is <b>kept on past orders</b>, which is why it is never edited or deleted.
                  </p>
                </Card>
              )}
            </div>
          </div>

          {adding && (
            <AddressForm customer={customer} onCancel={() => setAdding(false)} onAdded={() => {
              setAdding(false);
              setNotice("Address added. If it replaces an old one, retire the old one now.");
              reload();
            }} />
          )}

          {retiring && (
            <Modal title="Retire this address?" onClose={() => setRetiring(undefined)} footer={<>
              <Button onClick={() => setRetiring(undefined)}>Keep it</Button>
              <Button tone="danger" disabled={pending} onClick={() => retire(retiring)}>
                {pending ? "Retiring…" : "Retire address"}
              </Button>
            </>}>
              <div className="rounded-lg border border-neutral-200 px-4 py-3 text-sm">
                <div className="font-medium">{retiring.line1}</div>
                <div className="text-neutral-600">
                  {retiring.suburb} {retiring.state} {retiring.postcode}
                </div>
              </div>
              <p className="text-sm text-neutral-700">
                It stops being offered at checkout straight away. Orders already placed keep it — the record
                stays on file, still pointing at them.
              </p>
              {error && <ErrorBox error={error} />}
            </Modal>
          )}
        </>
      )}
    </div>
  );
}
