"use client";

import { useSyncExternalStore } from "react";

/**
 * A tiny localStorage-backed store read through `useSyncExternalStore`, so the server render and
 * hydration see "nothing chosen" and the browser's value then appears — with no effect-and-setState
 * dance and no hydration mismatch. If storage is blocked (a private window), a choice still works in
 * memory until the page reloads.
 */

const listeners = new Set<() => void>();
const memory = new Map<string, string | null>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return memory.get(key) ?? null;
  }
}

export function writeStored(key: string, value: string | null) {
  memory.set(key, value);
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // storage blocked: the in-memory value above still applies
  }
  listeners.forEach((listener) => listener());
}

/** A number stored under `key`, or undefined when nothing valid is stored. */
export function useStoredId(key: string): [number | undefined, (id: number | undefined) => void] {
  const raw = useSyncExternalStore(subscribe, () => readStored(key), () => null);
  const id = raw === null ? NaN : Number(raw);
  return [Number.isInteger(id) ? id : undefined, (next) => writeStored(key, next === undefined ? null : String(next))];
}
