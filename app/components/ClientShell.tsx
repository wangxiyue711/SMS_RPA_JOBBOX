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

  // Hide header/sidebar on the login page and any login subpaths
  // (covers `/login`, `/login/`, and `/login?next=...`)
  if (pathname.startsWith("/login")) {
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
