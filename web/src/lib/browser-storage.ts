"use client";

import { useSyncExternalStore } from "react";

/**
 * Small per-browser values — "My store", the cart — kept in localStorage and read through useSyncExternalStore:
 * the server render and hydration see nothing stored, then the browser's value appears, with no
 * effect-and-setState dance and no hydration mismatch. If storage is blocked (a private window), a value still
 * works in memory until the page reloads.
 */

const listeners = new Set<() => void>();
const memory = new Map<string, string | null>();

/** For useSyncExternalStore: `listener` runs after every write here, and when another tab writes. */
export function subscribeStored(listener: () => void) {
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

/** A whole number stored under `key`, or undefined when nothing valid is stored. */
export function useStoredId(key: string): [number | undefined, (id: number | undefined) => void] {
  const raw = useSyncExternalStore(subscribeStored, () => readStored(key), () => null);
  const id = raw === null ? NaN : Number(raw);
  return [Number.isInteger(id) ? id : undefined, (next) => writeStored(key, next === undefined ? null : String(next))];
}
