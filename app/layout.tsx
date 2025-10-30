import "./globals.css";

export const metadata = {
  title: "RoMeALL with rec-lab",
  description: "The robot works for me on all tasks.",
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
