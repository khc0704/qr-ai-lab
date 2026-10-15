"use client";

import { useSyncExternalStore } from "react";

const subscribeNoop = () => () => {};

function computeGreeting() {
  const h = new Date().getHours();
  return h < 12 ? "早安" : h < 18 ? "午安" : "晚安";
}

/** Server renders a neutral greeting; the client swaps in the time-of-day one after hydration (no mismatch). */
export function Greeting() {
  return <>{useSyncExternalStore(subscribeNoop, computeGreeting, () => "你好")}</>;
}
