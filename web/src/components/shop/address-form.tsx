"use client";

import { useState } from "react";

import { Button, ErrorBox, Field, inputClass, Modal, selectClass } from "@/components/ui";
import {
  type Address, type AddressCreate, type ApiError, api, call, type CustomerDetail, toApiError,
} from "@/lib/api/client";

const STATES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"];

/**
 * Add an address. Existing addresses are never edited (BR16): a customer adds the new one and retires the
 * old one, and orders already placed keep pointing at whichever address they were placed with.
 *
 * The server allocates the address number, so the form never invents one; after a successful save the
 * caller re-reads the customer rather than guessing what the record now looks like.
 */
export function AddressForm({ customer, onAdded, onCancel }: {
  customer: CustomerDetail;
  onAdded: (address: Address) => void;
  onCancel: () => void;
}) {
  const [values, setValues] = useState({ line1: "", suburb: "", state: "NSW", postcode: "" });
  const [error, setError] = useState<ApiError>();
  const [pending, setPending] = useState(false);

  const postcodeOk = /^\d{4}$/.test(values.postcode);
  const complete = values.line1.trim().length > 0 && values.suburb.trim().length > 0 && postcodeOk;

  async function submit() {
    if (!complete) return;
    setPending(true);
    setError(undefined);
    // The form only checks what makes a request worth sending; the database decides what is valid
    // (au_state_valid, au_postcode_format) and answers 409 with the rule's name.
    const body: AddressCreate = {
      line1: values.line1.trim(),
      suburb: values.suburb.trim(),
      state: values.state,
      postcode: values.postcode,
    };
    try {
      const address = await call(api.POST("/api/v1/customers/{customer_id}/addresses", {
        params: { path: { customer_id: customer.customer_id } },
        body,
      }));
      onAdded(address);
    } catch (failure) {
      // The typed values stay on screen so a rejected request can be corrected, not retyped.
      setError(toApiError(failure));
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal title="Add a delivery address" onClose={onCancel} footer={<>
      <Button onClick={onCancel}>Cancel</Button>
      <Button tone="primary" disabled={!complete || pending} onClick={submit}>
        {pending ? "Saving…" : "Save address"}
      </Button>
    </>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Field label="Street address">
            <input className={inputClass} value={values.line1} placeholder="12/40 Collins Street"
              onChange={(event) => setValues({ ...values, line1: event.target.value })} />
          </Field>
        </div>
        <Field label="Suburb">
          <input className={inputClass} value={values.suburb} placeholder="Melbourne"
            onChange={(event) => setValues({ ...values, suburb: event.target.value })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="State">
            <select className={selectClass} value={values.state}
              onChange={(event) => setValues({ ...values, state: event.target.value })}>
              {STATES.map((state) => <option key={state} value={state}>{state}</option>)}
            </select>
          </Field>
          <Field label="Postcode">
            <input className={inputClass} value={values.postcode} inputMode="numeric" maxLength={4}
              placeholder="3000"
              onChange={(event) => setValues({ ...values, postcode: event.target.value.replace(/\D/g, "") })} />
          </Field>
        </div>
      </div>
      <p className={`text-[13px] ${postcodeOk ? "text-muted" : "font-semibold text-warn-ink"}`}>
        Four digits. {postcodeOk ? "" : "Use the four-digit postcode, e.g. 3000."}
      </p>
      <p className="text-[13px] text-muted">
        The address is added, never edited: if this replaces an old one, retire the old one afterwards.
      </p>
      {error && <ErrorBox error={error} />}
    </Modal>
  );
}
