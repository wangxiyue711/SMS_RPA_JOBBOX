import React from "react";
import EmailUpdater from "./EmailUpdater";

export default function Header() {
  return (
    <header
      style={{
        padding: "12px 28px",
        borderBottom: "1px solid rgba(0,0,0,0.06)",
        background: "var(--bg)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div style={{ fontWeight: 700 }}>RPA_SMS &amp; JOBBOX</div>
        <div id="user-email" style={{ color: "var(--muted)" }}>
          未ログイン
        </div>
      </div>
      <EmailUpdater />
    </header>
  );
}
