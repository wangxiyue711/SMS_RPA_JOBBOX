import React from "react";
import EmailUpdater from "./EmailUpdater";

export default function Header() {
  return (
    <header className="site-header">
      <div className="header-inner">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className="brand-compact">
            <div className="brand-mark" aria-hidden />
            <div className="brand-text">
              <div className="brand-acronym">
                RoMe<span className="title-accent">ALL</span>
              </div>
              <div className="brand-sub">The robot works for me on all tasks.</div>
            </div>
          </div>
        </div>

        <div id="user-email" style={{ color: "var(--muted)" }}>
          未ログイン
        </div>
      </div>
      <EmailUpdater />
    </header>
  );
}
