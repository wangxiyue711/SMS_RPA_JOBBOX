"use client";

import React, { useState, useEffect } from "react";

export default function DashboardClient() {
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  useEffect(() => {
    const today = new Date();
    const end = today;
    const start = new Date();
    start.setDate(today.getDate() - 6);
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    setStartDate(fmt(start));
    setEndDate(fmt(end));
  }, []);

  return (
    <main className="main">
      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          marginBottom: 14,
        }}
      >
        <input
          type="date"
          aria-label="開始日"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          className="date-input"
        />
        <span style={{ color: "var(--muted)" }}>-</span>
        <input
          type="date"
          aria-label="終了日"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
          className="date-input"
        />
      </div>

      <div className="card-grid">
        <div className="stat-card">
          <div className="stat-label">実行数</div>
          <div className="stat-value">—</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">送信成功数</div>
          <div className="stat-value">—</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">送信失敗数</div>
          <div className="stat-value">—</div>
        </div>
      </div>

      <div
        style={{
          marginTop: 18,
          padding: 18,
          borderRadius: 10,
          background: "#fff",
          border: "1px solid rgba(48,48,48,0.04)",
        }}
      >
        <div
          style={{
            textAlign: "center",
            color: "var(--muted)",
            padding: 40,
          }}
        >
          日別推移はここに表示されます
        </div>
      </div>

      <section style={{ marginTop: 18 }}>
        <div
          style={{
            marginTop: 8,
            padding: 18,
            borderRadius: 10,
            background: "#fff",
            border: "1px solid rgba(48,48,48,0.04)",
          }}
        >
          <div
            style={{
              fontWeight: 700,
              marginBottom: 8,
              color: "var(--shade-2)",
            }}
          >
            実行履歴
          </div>
          <div
            style={{
              textAlign: "center",
              color: "var(--muted)",
              padding: 28,
            }}
          >
            実行履歴はここに表示されます
          </div>
        </div>
      </section>
    </main>
  );
}
