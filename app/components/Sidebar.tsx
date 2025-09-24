"use client";

import React, { useState } from "react";
import Link from "next/link";

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
  return (
    <aside className="sidebar">
      {/* HOME 链接，左对齐 */}
      <div style={{ marginBottom: 12, display: "flex", alignItems: "center" }}>
        <Link href="/dashboard" passHref legacyBehavior>
            <a
              className="sidebar-home-link"
              style={{
                fontSize: 22,
                fontWeight: 700,
                margin: 0,
                textDecoration: "none",
                color: "inherit",
                cursor: "pointer",
                paddingLeft: 0,
              }}
            >
              HOME
            </a>
        </Link>
      </div>

      {/* MENU 标题，左对齐，带下拉箭头 */}
      <div
        style={{
          fontSize: 22,
          fontWeight: 700,
          marginBottom: 8,
          display: "flex",
          alignItems: "center",
          cursor: "pointer",
          paddingLeft: 0,
        }}
        onClick={() => setMenuOpen((v) => !v)}
      >
        MENU
        <span
          style={{
            marginLeft: 6,
            transition: "transform 0.2s",
            transform: menuOpen ? "rotate(90deg)" : "rotate(0deg)",
          }}
        >
          {/* 高级下拉箭头 icon */}
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path
              d="M4.5 6l3.5 3.5L11.5 6"
              stroke="#303030"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
        </span>
      </div>

      {/* 下拉菜单，带 icon */}
      {/* 下拉菜单内容暂时为空，后续可添加 */}
      {menuOpen && (
        <ul style={{ paddingLeft: 0, margin: 0, transition: "all 0.2s" }}>
          {/* 菜单子项留空，后续可补充 */}
          <li style={{ listStyle: "none", marginBottom: 6 }}>
            <Link href="/rpa-settings" passHref legacyBehavior>
              <a className="sidebar-home-link" style={{ fontSize: 18, fontWeight: 500, textDecoration: "none", color: "inherit", padding: "2px 10px", borderRadius: "6px", display: "block" }}>
                RPA設定
              </a>
            </Link>
          </li>
        </ul>
      )}
    </aside>
  );
}
