"use client";

import React, { useEffect, useRef, useState } from "react";
import { getClientAuth } from "../../lib/firebaseClient";
import { getFirestore, collection, getDocs } from "firebase/firestore";

export default function DashboardClient() {
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<any>({});
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const isDown = useRef(false);
  const startX = useRef(0);
  const scrollLeft = useRef(0);

  useEffect(() => {
    const today = new Date();
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    if (!endDate) setEndDate(fmt(today));
    if (!startDate) {
      const s = new Date(
        today.getFullYear(),
        today.getMonth(),
        today.getDate() - 6
      );
      setStartDate(fmt(s));
    }
    loadStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startDate, endDate]);

  async function waitForAuthReady(timeout = 3000): Promise<any | null> {
    const auth = getClientAuth();
    if (!auth) return null;
    if (auth.currentUser) return auth.currentUser;
    return new Promise((resolve) => {
      const unsub = (auth as any).onAuthStateChanged((u: any) => {
        try {
          unsub();
        } catch {}
        resolve(u);
      });
      setTimeout(() => {
        try {
          unsub();
        } catch {}
        resolve(null);
      }, timeout);
    });
  }

  async function loadStats() {
    setLoading(true);
    try {
      const user = await waitForAuthReady();
      if (!user) throw new Error("未ログインです。ログインしてください。");
      const db = getFirestore();
      const uid = (user as any).uid;

      const collRef = collection(db, "accounts", uid, "sms_history");
      const snap = await getDocs(collRef);
      const rows: any[] = [];
      snap.forEach((d) => rows.push(d.data() as any));

      const parseDateToSec = (s: string, endOfDay = false) => {
        if (!s) return null;
        const parts = s.split("-").map((p) => Number(p));
        if (parts.length !== 3) return null;
        const d = new Date(
          parts[0],
          parts[1] - 1,
          parts[2],
          endOfDay ? 23 : 0,
          endOfDay ? 59 : 0,
          endOfDay ? 59 : 0
        );
        return Math.floor(d.getTime() / 1000);
      };

      const selStartSec = parseDateToSec(startDate || "", false);
      const selEndSec = parseDateToSec(endDate || "", true);

      const filteredRows = rows.filter((r) => {
        if (selStartSec === null || selEndSec === null) return true;
        let s: number | null = null;
        try {
          if (typeof r.sentAt === "number") s = r.sentAt;
          else if (r.sentAt && typeof r.sentAt.seconds === "number")
            s = r.sentAt.seconds;
          else if (typeof r.sent_at === "number") s = r.sent_at;
          else if (r.sent_at_seconds && typeof r.sent_at_seconds === "number")
            s = r.sent_at_seconds;
          else if (r.sent_at_ts && typeof r.sent_at_ts === "number")
            s = r.sent_at_ts;
        } catch (e) {
          s = null;
        }
        if (s === null) return true;
        return s >= selStartSec && s <= selEndSec;
      });

      const total = filteredRows.length;
      let sent = 0;
      let failed = 0;
      let targetOut = 0;
      filteredRows.forEach((r) => {
        const status = (r.status || "").toString();
        if (status === "target_out") {
          targetOut += 1;
          return;
        }
        if (status === "sent") {
          sent += 1;
          return;
        }
        const resp = r.response;
        if (resp !== undefined && resp !== null) {
          if (typeof resp === "object") {
            const sc = resp.status_code || resp.status || resp.code;
            const scNum = Number(sc);
            if (!Number.isNaN(scNum) && scNum >= 200 && scNum < 300) sent += 1;
            else failed += 1;
            return;
          } else {
            const scNum = Number(resp);
            if (!Number.isNaN(scNum) && scNum >= 200 && scNum < 300) sent += 1;
            else {
              if (String(resp).indexOf("200") >= 0) sent += 1;
              else failed += 1;
            }
            return;
          }
        }
        failed += 1;
      });

      const startSec =
        selStartSec !== null
          ? selStartSec
          : Math.floor(new Date().getTime() / 1000) - 6 * 86400;
      const endSec =
        selEndSec !== null
          ? selEndSec
          : Math.floor(new Date().getTime() / 1000);
      const days = Math.floor((endSec - startSec) / 86400) + 1;
      const dayCounts = new Array(Math.max(1, days)).fill(0);
      filteredRows.forEach((r) => {
        let s = null;
        try {
          if (typeof r.sentAt === "number") s = r.sentAt;
          else if (r.sentAt && typeof r.sentAt.seconds === "number")
            s = r.sentAt.seconds;
          else if (typeof r.sent_at === "number") s = r.sent_at;
          else if (r.sent_at_seconds && typeof r.sent_at_seconds === "number")
            s = r.sent_at_seconds;
          else if (r.sent_at_ts && typeof r.sent_at_ts === "number")
            s = r.sent_at_ts;
        } catch (e) {
          s = null;
        }
        if (s !== null) {
          const idx = Math.floor((s - startSec) / 86400);
          if (idx >= 0 && idx < dayCounts.length) dayCounts[idx] += 1;
        }
      });

      setStats({ total, sent, failed, targetOut, dayCounts, startSec, endSec });
    } catch (e) {
      console.error("loadStats error", e);
      setStats({ total: 0, sent: 0, failed: 0, targetOut: 0 });
    } finally {
      setLoading(false);
    }
  }

  // attach touch listeners to make the draggable div work on touch devices
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onTouchStart = (ev: TouchEvent) => {
      isDown.current = true;
      startX.current = ev.touches[0].pageX - (el.offsetLeft || 0);
      scrollLeft.current = el.scrollLeft;
    };
    const onTouchEnd = () => {
      isDown.current = false;
    };
    const onTouchMove = (ev: TouchEvent) => {
      if (!isDown.current) return;
      ev.preventDefault();
      const x = ev.touches[0].pageX - (el.offsetLeft || 0);
      const walk = x - startX.current;
      el.scrollLeft = scrollLeft.current - walk;
    };
    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchend", onTouchEnd);
    el.addEventListener("touchmove", onTouchMove as any, { passive: false });
    return () => {
      el.removeEventListener("touchstart", onTouchStart as any);
      el.removeEventListener("touchend", onTouchEnd as any);
      el.removeEventListener("touchmove", onTouchMove as any);
    };
  }, []);

  // Read theme colors from CSS variables (fallback to current blue palette)
  const themeColors =
    typeof window !== "undefined"
      ? (() => {
          try {
            const s = getComputedStyle(document.documentElement);
            return [
              s.getPropertyValue("--shade-1").trim() || "#000000",
              s.getPropertyValue("--shade-2").trim() || "#1976d2",
              s.getPropertyValue("--shade-3").trim() || "#5e5e5e",
              s.getPropertyValue("--shade-4").trim() || "#64b5f6",
              s.getPropertyValue("--shade-5").trim() || "#c6c6c6",
            ];
          } catch (e) {
            return ["#000000", "#1976d2", "#5e5e5e", "#64b5f6", "#c6c6c6"];
          }
        })()
      : ["#000000", "#1976d2", "#5e5e5e", "#64b5f6", "#c6c6c6"];

  const strokeColor = themeColors[1] || "#1976d2"; // primary accent
  const areaStart = themeColors[3] || "#64b5f6"; // lighter fill
  const areaEnd = themeColors[1] || strokeColor; // fade to accent

  return (
    <main className="main">
      <div className="module-shell">
        <div
          className="stat-grid"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
            gap: 16,
            alignItems: "stretch",
          }}
        >
          <div>
            <div className="stat-card">
              <div className="stat-label">合計実行数</div>
              <div className="stat-value">
                {loading ? "..." : stats.total ?? 0}
              </div>
            </div>
          </div>
          <div>
            <div className="stat-card">
              <div className="stat-label">送信成功数</div>
              <div className="stat-value">
                {loading ? "..." : stats.sent ?? 0}
              </div>
            </div>
          </div>
          <div>
            <div className="stat-card">
              <div className="stat-label">送信失敗数</div>
              <div className="stat-value">
                {loading ? "..." : stats.failed ?? 0}
              </div>
            </div>
          </div>
          <div>
            <div className="stat-card">
              <div className="stat-label">対象外</div>
              <div className="stat-value">
                {loading ? "..." : stats.targetOut ?? 0}
              </div>
            </div>
          </div>
        </div>

        <div className="module-wrapper">
          <div style={{ marginTop: 18 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 8,
              }}
            >
              <div style={{ fontWeight: 700 }}>RPA発信回数</div>
            </div>

            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                justifyContent: "flex-start",
                marginBottom: 8,
              }}
            >
              <label style={{ fontSize: 12, color: "var(--muted)" }}>
                開始
              </label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
              <label style={{ fontSize: 12, color: "var(--muted)" }}>
                終了
              </label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>

            {loading ? (
              <div>読み込み中...</div>
            ) : (
              (() => {
                const counts: number[] = stats.dayCounts || [];
                const startSec: number = stats.startSec || 0;
                const max = counts.length ? Math.max(...counts) : 0;
                const labels = [] as string[];
                for (let i = 0; i < counts.length; i++) {
                  const d = new Date((startSec + i * 86400) * 1000);
                  labels.push(`${d.getMonth() + 1}/${d.getDate()}`);
                }
                return (
                  <div>
                    <div
                      className="draggable"
                      ref={(el) => {
                        if (el) scrollRef.current = el as HTMLDivElement;
                      }}
                      onMouseDown={(e) => {
                        isDown.current = true;
                        startX.current =
                          e.pageX - (scrollRef.current?.offsetLeft || 0);
                        scrollLeft.current = scrollRef.current?.scrollLeft || 0;
                      }}
                      onMouseLeave={() => {
                        isDown.current = false;
                      }}
                      onMouseUp={() => {
                        isDown.current = false;
                      }}
                      onMouseMove={(e) => {
                        if (!isDown.current || !scrollRef.current) return;
                        e.preventDefault();
                        const x = e.pageX - scrollRef.current.offsetLeft;
                        const walk = x - startX.current;
                        scrollRef.current.scrollLeft =
                          scrollLeft.current - walk;
                      }}
                    >
                      <div className="line-chart-row">
                        {/* compute layout values */}
                        {(() => {
                          const colWidth = 72; // width per day column
                          const chartHeight = 92; // internal chart height
                          const svgHeight = chartHeight + 12; // leave space for top/bottom
                          const svgWidth = Math.max(
                            counts.length * colWidth,
                            200
                          );

                          const pts = counts.map((c: number, i: number) => {
                            const x = i * colWidth + colWidth / 2;
                            const y = max
                              ? Math.round((1 - c / max) * chartHeight) + 6
                              : chartHeight + 6;
                            return { x, y, v: c };
                          });

                          const pathD = pts.length
                            ? pts
                                .map(
                                  (p, i) =>
                                    `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`
                                )
                                .join(" ")
                            : "";

                          // area under curve path (closed)
                          const areaD = pts.length
                            ? "M " +
                              pts.map((p) => `${p.x} ${p.y}`).join(" L ") +
                              ` L ${pts.length ? pts[pts.length - 1].x : 0} ${
                                chartHeight + 8
                              } L ${pts.length ? pts[0].x : 0} ${
                                chartHeight + 8
                              } Z`
                            : "";

                          return (
                            <div
                              className="line-chart"
                              style={{ width: `${svgWidth}px` }}
                            >
                              <svg
                                width={svgWidth}
                                height={svgHeight}
                                viewBox={`0 0 ${svgWidth} ${svgHeight}`}
                                preserveAspectRatio="xMinYMin meet"
                                role="img"
                                aria-label="折线图"
                              >
                                <defs>
                                  <linearGradient
                                    id="lcg"
                                    x1="0"
                                    x2="0"
                                    y1="0"
                                    y2="1"
                                  >
                                    <stop
                                      offset="0%"
                                      stopColor={areaStart}
                                      stopOpacity="0.25"
                                    />
                                    <stop
                                      offset="100%"
                                      stopColor={areaEnd}
                                      stopOpacity="0"
                                    />
                                  </linearGradient>
                                </defs>

                                {/* area */}
                                {areaD && (
                                  <path
                                    d={areaD}
                                    fill="url(#lcg)"
                                    stroke="none"
                                  />
                                )}

                                {/* line */}
                                {pathD && (
                                  <path
                                    d={pathD}
                                    fill="none"
                                    stroke={strokeColor}
                                    strokeWidth={2}
                                    strokeLinejoin="round"
                                    strokeLinecap="round"
                                  />
                                )}

                                {/* points */}
                                {pts.map((p, idx) => (
                                  <g key={idx}>
                                    <circle
                                      cx={p.x}
                                      cy={p.y}
                                      r={4}
                                      fill="#ffffff"
                                      stroke={strokeColor}
                                      strokeWidth={2}
                                    />
                                    <title>{`${labels[idx]}: ${p.v}`}</title>
                                  </g>
                                ))}
                              </svg>

                              <div
                                className="line-chart__labels"
                                style={{ width: `${svgWidth}px` }}
                              >
                                {labels.map((lab, i) => (
                                  <div
                                    key={i}
                                    className="line-chart__label"
                                    style={{ width: `${colWidth}px` }}
                                  >
                                    {lab}
                                  </div>
                                ))}
                              </div>
                            </div>
                          );
                        })()}
                      </div>
                    </div>
                  </div>
                );
              })()
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
