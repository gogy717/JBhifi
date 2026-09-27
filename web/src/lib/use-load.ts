"use client";

import { useEffect, useEffectEvent, useState } from "react";

import { type ApiError, toApiError } from "./api/client";

/**
 * Load data when `key` changes (or reload() is called). While a new load runs, the previous data
 * stays on screen and `loading` is true.
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

  return {
    data: result?.data,
    error: result?.key === requestKey ? result.error : undefined,
    loading: result?.key !== requestKey,
    reload: () => setVersion((v) => v + 1),
    /** Replace the loaded data locally, e.g. with a row the API just returned. */
    setData: (update: (data: T) => T) =>
      setResult((r) => (r?.data === undefined ? r : { ...r, data: update(r.data) })),
  };
}
