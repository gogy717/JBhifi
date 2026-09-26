/**
 * The shared dialog and error box (T05): a dialog is operable with the keyboard alone, and the controls
 * a screen reader reads out have names.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/client";
import { Button, ErrorBox, Field, inputClass, Modal } from "@/components/ui";

function Opener() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Adjust…</button>
      {open && (
        <Modal title="Adjust stock" onClose={() => setOpen(false)}
          footer={<Button tone="primary">Save adjustment</Button>}>
          <Field label="Units">
            <input className={inputClass} />
          </Field>
        </Modal>
      )}
    </>
  );
}

describe("Modal", () => {
  it("is named, keeps focus inside, closes on Escape and gives focus back", async () => {
    const user = userEvent.setup();
    render(<Opener />);

    const opener = screen.getByRole("button", { name: "Adjust…" });
    await user.click(opener);

    const dialog = screen.getByRole("dialog", { name: "Adjust stock" });
    expect(dialog.contains(document.activeElement)).toBe(true);           // focus starts inside
    expect(document.body.style.overflow).toBe("hidden");                 // the page behind is not scrollable

    const save = screen.getByRole("button", { name: "Save adjustment" });
    save.focus();
    await user.tab();                                                    // Tab past the last control
    expect(dialog.contains(document.activeElement)).toBe(true);           // ...stays inside the dialog
    expect(document.activeElement).not.toBe(save);

    await user.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(opener);                         // focus returns to what opened it
    expect(document.body.style.overflow).not.toBe("hidden");
  });
});

describe("controls", () => {
  it("labels its fields and offers a retry on a failure the screen cannot work without", async () => {
    const user = userEvent.setup();
    let retried = 0;
    render(
      <>
        <Field label="Units"><input className={inputClass} /></Field>
        <ErrorBox error={new ApiError(0, "network_error", "Can't reach the API.")} onRetry={() => retried++} />
      </>,
    );

    expect(screen.getByLabelText("Units")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(retried).toBe(1);
  });
});
