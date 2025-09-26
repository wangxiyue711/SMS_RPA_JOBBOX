"use client";

import React from "react";
import { usePathname } from "next/navigation";
import Header from "./Header";
import Sidebar from "./Sidebar";

export default function ClientShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname() ?? "";

  // Hide header/sidebar on the login page and API-related pages where
  // we render a minimal response (these routes shouldn't show the app shell).
  // Covers `/login`, `/api`, `/api-settings`, and their subpaths.
  // Hide header/sidebar on the login page, and on Next.js API routes
  // (we keep UI pages like `/api-settings` visible). This covers
  // `/api` and any `/api/...` route while allowing `/api-settings`.
  if (
    pathname.startsWith("/login") ||
    pathname === "/api" ||
    pathname.startsWith("/api/")
  ) {
    return <>{children}</>;
  }

  return (
    <>
      <Header />
      <div className="content-wrap">
        <div className="dashboard">
          <Sidebar heading="HOME" />
          <main>{children}</main>
        </div>
      </div>
    </>
  );
}
