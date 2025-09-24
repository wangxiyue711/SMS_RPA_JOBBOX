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
        <div className="content-wrap">
          <div className="dashboard">
            <Sidebar heading="HOME" />
            <main>{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
