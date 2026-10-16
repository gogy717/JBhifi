"use client";

import { type ReactNode, useState } from "react";

import { AddressForm } from "@/components/shop/address-form";
import { useShop } from "@/components/shop/context";
import { CustomerGate } from "@/components/shop/customer-gate";
import { Callout, Crumbs, DetailRow, focusRing, PageIntro, SectionTitle } from "@/components/shop/page-parts";
import { Badge, Button, Card, ErrorBox, Modal } from "@/components/ui";
import { type Address, type ApiError, api, call, type CustomerDetail, toApiError } from "@/lib/api/client";
import { formatDate } from "@/lib/format";

export default function AccountPage() {
  return (
    <div className="space-y-8">
      <title>My account · TechLight</title>
      <div className="space-y-4">
        <Crumbs trail={[["Home", "/"], ["My account"]]} />
        <PageIntro title="My account">Your details, and the addresses an order can be delivered to.</PageIntro>
      </div>
      <CustomerGate what="see your details and addresses">
        {(customer) => <Account customer={customer} />}
      </CustomerGate>
    </div>
  );
}

function Account({ customer }: { customer: CustomerDetail }) {
  const { reloadCustomer } = useShop();
  const [adding, setAdding] = useState(false);
  const [retiring, setRetiring] = useState<Address>();
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<ApiError>();
  const [pending, setPending] = useState(false);

  async function retire(address: Address) {
    setPending(true);
    setError(undefined);
    try {
      // The only change an address accepts (BR16). Retiring one that is already retired is answered the same.
      await call(api.PATCH("/api/v1/customers/{customer_id}/addresses/{address_no}", {
        params: { path: { customer_id: customer.customer_id, address_no: address.address_no } },
        body: { is_active: false },
      }));
      setRetiring(undefined);
      setNotice(`Address #${address.address_no} (${address.line1}) is retired. Orders already placed keep it.`);
      reloadCustomer();
    } catch (failure) {
      setError(toApiError(failure));
    } finally {
      setPending(false);
    }
  }

  const current = customer.addresses.filter((address) => address.is_active);
  const past = customer.addresses.filter((address) => !address.is_active);

  const initials = customer.full_name.split(/\s+/).map((part) => part[0]).slice(0, 2).join("").toUpperCase();

  return (
    <>
      {notice && (
        <Callout tone="ok" role="status">
          {notice}
          <button type="button" className="ml-3 font-semibold underline" onClick={() => setNotice(undefined)}>dismiss</button>
        </Callout>
      )}
      {error && !retiring && <ErrorBox error={error} onClose={() => setError(undefined)} />}

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <section className="min-w-0">
          <SectionTitle>Your details</SectionTitle>
          <Card>
            <div className="flex items-center gap-4 border-b border-line px-5 py-5">
              <span aria-hidden="true" className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full
                bg-brand-soft font-display text-[20px] font-bold text-brand-strong">
                {initials}
              </span>
              <div className="min-w-0">
                <div className="font-display text-[20px] font-bold tracking-[-0.01em]">{customer.full_name}</div>
                <div className="truncate text-[14px] text-muted">{customer.email}</div>
              </div>
            </div>
            <dl className="divide-y divide-line">
              <DetailRow label="Name">{customer.full_name}</DetailRow>
              <DetailRow label="Email"><span className="font-mono text-[13px] break-all">{customer.email}</span></DetailRow>
              <DetailRow label="Phone">{customer.phone ?? "—"}</DetailRow>
              <DetailRow label="Customer since">{formatDate(customer.created_at)}</DetailRow>
              <DetailRow label="Customer #"><span className="tabular-nums">{customer.customer_id}</span></DetailRow>
            </dl>
            <p className="border-t border-line px-5 py-4 text-[13px] text-muted">
              The email is unique and stored in lower case (BR01). You sign in with Clerk; the API links that sign-in
              to this record.
            </p>
          </Card>
        </section>

        <div className="min-w-0 space-y-14">
          <section>
            <SectionTitle aside={<Button size="sm" tone="primary" onClick={() => setAdding(true)}>Add address</Button>}>
              Current delivery addresses
            </SectionTitle>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {current.map((address) => (
                <AddressCard key={address.address_no} address={address}
                  action={<Button size="sm" onClick={() => setRetiring(address)}>Retire…</Button>} />
              ))}
              <button type="button" onClick={() => setAdding(true)}
                className={`flex min-h-36 flex-col items-center justify-center gap-2 rounded-card border-2 border-dashed
                  border-line p-5 text-[15px] font-bold text-muted transition-colors hover:border-ink hover:text-ink
                  ${focusRing}`}>
                <span aria-hidden="true" className="text-[24px] leading-none">+</span>
                {current.length === 0 ? "No current address. Add one before ordering delivery." : "Add an address"}
              </button>
            </div>
            <p className="mt-4 text-[13px] leading-relaxed text-muted">
              Retiring replaces an address without rewriting it: orders already placed keep the address they were
              placed with (BR16), and checkout only offers current ones (BR17).
            </p>
          </section>

          {past.length > 0 && (
            <section>
              <SectionTitle>Past addresses</SectionTitle>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {past.map((address) => (
                  <AddressCard key={address.address_no} address={address} retired action={<Badge>retired</Badge>} />
                ))}
              </div>
              <p className="mt-4 text-[13px] text-muted">
                An address is <b className="text-ink">kept on past orders</b>, which is why it is never edited or deleted.
              </p>
            </section>
          )}
        </div>
      </div>

      {adding && (
        <AddressForm customer={customer} onCancel={() => setAdding(false)} onAdded={(address) => {
          setAdding(false);
          setNotice(`Address #${address.address_no} added. If it replaces an old one, retire the old one now.`);
          reloadCustomer();
        }} />
      )}

      {retiring && (
        <Modal title="Retire this address?" onClose={() => setRetiring(undefined)} footer={<>
          <Button onClick={() => setRetiring(undefined)}>Keep it</Button>
          <Button tone="danger" disabled={pending} onClick={() => retire(retiring)}>
            {pending ? "Retiring…" : "Retire address"}
          </Button>
        </>}>
          <div className="rounded-tile bg-sand px-4 py-3 text-[15px]">
            <div className="font-bold">{retiring.line1}</div>
            <div className="text-muted">{retiring.suburb} {retiring.state} {retiring.postcode}</div>
          </div>
          <p className="text-[15px]">
            It stops being offered at checkout straight away. Orders already placed keep it — the record stays on
            file, still pointing at them.
          </p>
          {error && <ErrorBox error={error} />}
        </Modal>
      )}
    </>
  );
}

/** One address as a card; a retired one is quieter. */
function AddressCard({ address, action, retired = false }: { address: Address; action: ReactNode; retired?: boolean }) {
  return (
    <article className={`flex flex-col gap-4 rounded-card border border-line p-5 ${retired ? "bg-sand" : "bg-white"}`}>
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-[14px]
          ${retired ? "bg-white" : "bg-brand-soft"}`}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" className={retired ? "text-muted" : "text-brand-strong"}>
            <path d="M3 10.5 12 3l9 7.5" />
            <path d="M5 9v11h14V9" />
            <path d="M10 20v-6h4v6" />
          </svg>
        </span>
        <div className="min-w-0">
          <div className={`font-bold ${retired ? "text-muted" : ""}`}>{address.line1}</div>
          <div className="text-[14px] text-muted">{address.suburb} {address.state} {address.postcode}</div>
        </div>
      </div>
      <div className="mt-auto flex items-center justify-between gap-3">
        <span className="text-[13px] text-muted tabular-nums">Address #{address.address_no}</span>
        {action}
      </div>
    </article>
  );
}
