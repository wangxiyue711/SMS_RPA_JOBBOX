"use client";

import { useEffect } from "react";
import { getClientAuth } from "../../lib/firebaseClient";

export default function EmailUpdater() {
  useEffect(() => {
    try {
      const auth = getClientAuth();
      if (!auth) return;
      const setEmail = (email: string | null) => {
        const el = document.getElementById("user-email");
        if (el) el.textContent = email ?? "未ログイン";
      };
      // set initial
      setEmail(auth.currentUser?.email ?? null);
      const unsub = auth.onAuthStateChanged((u) => setEmail(u?.email ?? null));
      return () => unsub();
    } catch (err) {
      // swallow errors during client-side update to avoid breaking hydration
      // console.error('EmailUpdater error', err);
    }
  }, []);

  return null;
}
