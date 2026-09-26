"use client";

import { useEffect, useEffectEvent, useState } from "react";

import { type ApiError, toApiError } from "./api/client";

/**
 * Load data when `key` changes (or reload() is called). While a new load runs, the previous data
 * stays on screen and `loading` is true.
 *
 * `key` names the resource, not just the request: `inventory:1` and `inventory:2` are different
 * records even though the same component renders both. Two things follow from that, and both matter
 * when someone switches store, product or filter while a request is still in flight:
 *
 * - `isCurrent` is false until the data on screen belongs to the key being asked for now, so a screen
 *   can refuse to make loading or stale rows actionable.
 * - `setData(key, update)` applies an update only when the data still belongs to that key. A result
 *   that arrives after the view moved on is dropped instead of written into another store's rows.
 */
export function useLoad<T>(key: string, load: () => Promise<T>) {
  const [version, setVersion] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: T; error?: ApiError }>();
  const requestKey = `${key}#${version}`;
  const runLoad = useEffectEvent(load);

  useEffect(() => {
    let cancelled = false;
    runLoad().then(
      (data) => !cancelled && setResult({ key: requestKey, data }),
      (error) => !cancelled && setResult({ key: requestKey, error: toApiError(error) }),
    );
    return () => {
      cancelled = true;
    };
  }, [requestKey]);

  const settled = result?.key === requestKey;
  return {
    data: result?.data,
    error: settled ? result.error : undefined,
    loading: !settled,
    /** True when the data on screen came from this key, rather than a request still on its way. */
    isCurrent: settled,
    reload: () => setVersion((v) => v + 1),
    /** Replace the loaded data locally, e.g. with a row the API just returned — but only while that
     *  data still belongs to `expectedKey`, so a late mutation cannot rewrite another record. */
    setData: (expectedKey: string, update: (data: T) => T) =>
      setResult((r) => {
        if (r?.data === undefined) return r;
        if (r.key !== requestKey || expectedKey !== key) return r;    // the screen has moved on
        return { ...r, data: update(r.data) };
      }),
  };
}
