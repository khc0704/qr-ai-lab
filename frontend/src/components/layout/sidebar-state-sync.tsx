"use client";

import { useEffect } from "react";
import { useSidebar } from "@/components/ui/sidebar";

/**
 * Restores the collapsed state after mount from the cookie SidebarProvider writes itself. Render it inside the
 * Suspense boundary that holds <Sidebar>, so the effect fires after that boundary hydrated (otherwise the provider
 * already says "collapsed" when the streamed sidebar HTML hydrates → attribute mismatch).
 * Reading cookies() in the (app) layout would make every route dynamic under Cache Components,
 * so the server always renders the sidebar expanded and this corrects it on the client.
 */
export function SidebarStateSync() {
  const { setOpen } = useSidebar();
  useEffect(() => {
    const m = document.cookie.match(/(?:^|; )sidebar_state=([^;]*)/);
    if (m && m[1] === "false") setOpen(false);
  }, [setOpen]);
  return null;
}
