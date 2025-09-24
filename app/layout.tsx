import "./globals.css";

export const metadata = {
  title: "RPA_JOBBOX",
  description: "Login page with Firebase auth",
};

import React from "react";
import Sidebar from "./components/Sidebar";
import Header from "./components/Header";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body>
        <Header />
        <div style={{ display: "flex" }}>
          <Sidebar heading="HOME" />
          <main style={{ flex: 1 }}>{children}</main>
        </div>
      </body>
    </html>
  );
}
