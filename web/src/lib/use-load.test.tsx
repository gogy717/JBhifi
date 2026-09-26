/**
 * The shared loader's contract (T05): which response is allowed to reach the screen once the viewer has
 * moved to another store, product or filter, and what a local update may touch.
 *
 * The network is mocked at the promise boundary — the test controls *when* each response arrives — and
 * the race itself is real.
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ApiError } from "./api/client";
import { useLoad } from "./use-load";

/** A promise the test resolves by hand, so an answer can arrive after the screen has moved on. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function Ledger({ resourceKey, load }: { resourceKey: string; load: (key: string) => Promise<string[]> }) {
  const { data, error, isCurrent, loading, reload, setData } = useLoad(resourceKey, () => load(resourceKey));
  return (
    <div>
      <p data-testid="rows">{(data ?? []).join(" | ")}</p>
      <p data-testid="error">{error ? `error:${error.code}` : ""}</p>
      <p data-testid="loading">{String(loading)}</p>
      <p data-testid="current">{String(isCurrent)}</p>
      <button type="button" onClick={() => setData(resourceKey, (rows) => [...rows, "local"])}>
        write to {resourceKey}
      </button>
      <button type="button" onClick={reload}>reload</button>
    </div>
  );
}

function show(initialKey: string, load: (key: string) => Promise<string[]>) {
  const view = render(<Ledger resourceKey={initialKey} load={load} />);
  return {
    /** Move the screen to another resource, the way a store or product picker would. */
    moveTo: (key: string) => view.rerender(<Ledger resourceKey={key} load={load} />),
  };
}

const rows = () => screen.getByTestId("rows").textContent;
const error = () => screen.getByTestId("error").textContent;
const loading = () => screen.getByTestId("loading").textContent;
const isCurrent = () => screen.getByTestId("current").textContent;

describe("useLoad", () => {
  it("ignores an answer that arrives after the screen moved to another store", async () => {
    const storeOne = deferred<string[]>();
    const storeTwo = deferred<string[]>();
    const load = (key: string) => (key === "store:1" ? storeOne.promise : storeTwo.promise);

    const { moveTo } = show("store:1", load);
    expect(rows()).toBe("");                    // nothing from a previous screen is shown as store 1
    expect(loading()).toBe("true");

    moveTo("store:2");                          // the shopper switches store before store 1 answers
    await act(async () => storeTwo.resolve(["B item"]));
    expect(rows()).toBe("B item");
    expect(isCurrent()).toBe("true");

    await act(async () => storeOne.resolve(["A item"]));   // store 1's answer finally arrives
    expect(rows()).toBe("B item");                          // and cannot take over store 2's screen
    expect(isCurrent()).toBe("true");
  });

  it("refuses to write a result that belongs to another resource", async () => {
    const user = userEvent.setup();
    const storeOne = deferred<string[]>();
    const storeTwo = deferred<string[]>();
    const load = (key: string) => (key === "store:1" ? storeOne.promise : storeTwo.promise);

    const { moveTo } = show("store:1", load);
    await act(async () => storeOne.resolve(["A item"]));
    expect(rows()).toBe("A item");

    moveTo("store:2");
    await act(async () => storeTwo.resolve(["B item"]));
    expect(rows()).toBe("B item");

    // A late response for store 1 is applied by the old render's closure; it must be dropped.
    await user.click(screen.getByRole("button", { name: "write to store:2" }));
    expect(rows()).toBe("B item | local");
    expect(isCurrent()).toBe("true");
  });

  it("keeps the rows on screen through a same-key reload, but stops calling them current", async () => {
    const user = userEvent.setup();
    const first = deferred<string[]>();
    const second = deferred<string[]>();
    let calls = 0;
    const load = () => (calls++ === 0 ? first.promise : second.promise);

    show("store:1", load);
    await act(async () => first.resolve(["A item"]));
    expect(rows()).toBe("A item");
    expect(isCurrent()).toBe("true");

    await user.click(screen.getByRole("button", { name: "reload" }));
    expect(rows()).toBe("A item");              // the old rows stay visible while the refresh runs
    expect(isCurrent()).toBe("false");          // so a screen must not offer to change stock from them
    expect(loading()).toBe("true");

    await act(async () => second.resolve(["A item (fresh)"]));
    expect(rows()).toBe("A item (fresh)");
    expect(isCurrent()).toBe("true");
  });

  it("surfaces a rejected request and recovers when the screen is reloaded", async () => {
    const user = userEvent.setup();
    const refused = deferred<string[]>();
    let calls = 0;
    const load = () => (calls++ === 0 ? refused.promise : Promise.resolve(["A item"]));

    show("store:1", load);
    await act(async () => {
      refused.reject(new ApiError(409, "br03_inventory_qty_nonneg", "Not enough stock."));
    });
    expect(error()).toBe("error:br03_inventory_qty_nonneg");
    expect(rows()).toBe("");

    await user.click(screen.getByRole("button", { name: "reload" }));
    expect(error()).toBe("");
    expect(rows()).toBe("A item");
    expect(isCurrent()).toBe("true");
  });
});
