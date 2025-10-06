"use client";

import React, { useState } from "react";
import Link from "next/link";
import { getClientAuth } from "../../lib/firebaseClient";

type SidebarItem = {
  label: string;
  href: string;
};

type SidebarProps = {
  title?: string;
  items?: SidebarItem[];
  heading?: string | null;
};

export default function Sidebar({
  title = "MENU",
  items = [{ label: "HOME", href: "/dashboard" }],
  heading = null,
}: SidebarProps) {
  const pathname =
    typeof window !== "undefined" ? window.location.pathname : "";
  const [menuOpen, setMenuOpen] = useState(false);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

  return (
    <aside
      className="sidebar"
      style={{
        display: "flex",
        flexDirection: "column",
        maxHeight: "calc(100vh - 64px)",
        overflowY: "auto",
      }}
    >
      {/* Primary nav items with equal spacing */}
      <nav
        aria-label="Primary"
        style={{ display: "flex", flexDirection: "column", gap: 10 }}
      >
        {/* HOME */}
        <Link href="/dashboard" passHref legacyBehavior>
          <a
            className="sidebar-home-link"
            style={{
              fontSize: 22,
              fontWeight: 700,
              textDecoration: "none",
              color: "inherit",
              paddingLeft: 0,
            }}
          >
            <span className="sidebar-icon" aria-hidden>
              <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path
                  d="M3 11.5L12 4l9 7.5"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M5 11.5v7.5a1 1 0 0 0 1 1h3v-5h6v5h3a1 1 0 0 0 1-1v-7.5"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
            HOME
          </a>
        </Link>

        {/* MENU toggle */}
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-expanded={menuOpen}
          className="sidebar-home-link"
          style={{
            fontSize: 22,
            fontWeight: 700,
            textAlign: "left",
            background: "none",
            border: 0,
            paddingLeft: 0,
            cursor: "pointer",
          }}
        >
          <span className="sidebar-icon" aria-hidden>
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M3 7h18M3 12h18M3 17h18"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          MENU
          <span
            style={{
              marginLeft: 6,
              transition: "transform 0.2s",
              transform: menuOpen ? "rotate(0deg)" : "rotate(90deg)",
            }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M4.5 6l3.5 3.5L11.5 6"
                stroke="#303030"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </span>
        </button>

        {/* Dropdown content directly under MENU */}
        {menuOpen && (
          <div style={{ marginTop: 4, marginLeft: 8 }}>
            <ul style={{ paddingLeft: 0, margin: 0, transition: "all 0.2s" }}>
              <li style={{ listStyle: "none", marginBottom: 6 }}>
                <Link href="/rpa-settings" passHref legacyBehavior>
                  <a
                    className="sidebar-home-link"
                    style={{
                      fontSize: 18,
                      fontWeight: 500,
                      textDecoration: "none",
                      color: "inherit",
                      padding: "2px 10px",
                      borderRadius: "6px",
                      display: "block",
                    }}
                  >
                    1.アカウント設定
                  </a>
                </Link>
              </li>
              <li style={{ listStyle: "none", marginBottom: 6 }}>
                <Link href="/mail-settings" passHref legacyBehavior>
                  <a
                    className="sidebar-home-link"
                    style={{
                      fontSize: 18,
                      fontWeight: 500,
                      textDecoration: "none",
                      color: "inherit",
                      padding: "2px 10px",
                      borderRadius: "6px",
                      display: "block",
                    }}
                  >
                    2.メール設定
                  </a>
                </Link>
              </li>
              <li style={{ listStyle: "none", marginBottom: 6 }}>
                <Link href="/target-settings" passHref legacyBehavior>
                  <a
                    className="sidebar-home-link"
                    style={{
                      fontSize: 18,
                      fontWeight: 500,
                      textDecoration: "none",
                      color: "inherit",
                      padding: "2px 10px",
                      borderRadius: "6px",
                      display: "block",
                    }}
                  >
                    3.対象設定
                  </a>
                </Link>
              </li>
              <li style={{ listStyle: "none", marginBottom: 6 }}>
                <Link href="/api-settings" passHref legacyBehavior>
                  <a
                    className="sidebar-home-link"
                    style={{
                      fontSize: 18,
                      fontWeight: 500,
                      textDecoration: "none",
                      color: "inherit",
                      padding: "2px 10px",
                      borderRadius: "6px",
                      display: "block",
                    }}
                  >
                    4.API設定
                  </a>
                </Link>
              </li>
            </ul>
          </div>
        )}

        {/* HISTORY always visible to keep equal gaps */}
        <Link href="/history" passHref legacyBehavior>
          <a
            className="sidebar-home-link"
            style={{
              fontSize: 22,
              fontWeight: 700,
              textDecoration: "none",
              color: "inherit",
              paddingLeft: 0,
            }}
          >
            <span className="sidebar-icon" aria-hidden>
              <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path
                  d="M21 12a9 9 0 1 1-3-6.5"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M12 7v6l4 2"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
            HISTORY
          </a>
        </Link>

        {/* LOGOUT inline (no longer pinned to bottom) */}
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setShowLogoutConfirm(true);
          }}
          className="sidebar-home-link"
          style={{
            fontSize: 22,
            fontWeight: 700,
            textDecoration: "none",
            color: "inherit",
            paddingLeft: 0,
          }}
        >
          <span className="sidebar-icon" aria-hidden>
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path
                d="M12 2v10"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M5 10.5a7 7 0 1 0 14 0"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          LOGOUT
        </a>
      </nav>

      {/* Logout confirmation modal */}
      {showLogoutConfirm && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-title">ログアウトの確認</div>
            <div className="modal-body">ログアウトしてもよろしいですか？</div>
            <div className="modal-actions">
              <button
                className="btn"
                onClick={() => {
                  const auth = getClientAuth();
                  if (auth && typeof auth.signOut === "function") {
                    auth.signOut();
                  }
                  if (typeof window !== "undefined") {
                    window.location.href = "/login";
                  }
                }}
              >
                ログアウト
              </button>
              <button
                className="btn btn-gray"
                onClick={() => setShowLogoutConfirm(false)}
              >
                キャンセル
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
