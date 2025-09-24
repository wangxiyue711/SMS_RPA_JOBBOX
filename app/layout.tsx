import "./globals.css";

export const metadata = {
  title: "RPA_JOBBOX",
  description: "Login page with Firebase auth",
};

import React from "react";
import ClientShell from "./components/ClientShell";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body>
        <ClientShell>{children}</ClientShell>
      </body>
    </html>
  );
}
