"use client";

import React, { useEffect, useState } from "react";
import { getClientAuth } from "../../lib/firebaseClient";
import {
  getFirestore,
  collection,
  query,
  orderBy,
  limit,
  getDocs,
} from "firebase/firestore";

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

export default function HistoryPage() {
  const [rows, setRows] = useState<any[]>([]);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 10;
  const [pageInput, setPageInput] = useState("1");
  const [loading, setLoading] = useState(false);
  const [loadedOnce, setLoadedOnce] = useState(false);
  const [serverRows, setServerRows] = useState<any[] | null>(null);

  useEffect(() => {
    loadHistory();
  }, []);

  // keep pageInput in sync when page or rows change
  useEffect(() => {
    setPageInput(String(page + 1));
  }, [page, rows]);

  async function loadHistory() {
    setLoading(true);
    try {
      const user = await waitForAuthReady();
      if (!user) throw new Error("未ログインです。ログインしてください。");
      const db = getFirestore();
      const uid = (user as any).uid;
      // collection path: accounts/{uid}/sms_history
      const collRef = collection(db, "accounts", uid, "sms_history");
      const q = query(collRef, orderBy("sentAt", "desc"), limit(100));
      const snap = await getDocs(q);
      const out: any[] = [];
      snap.forEach((d) => {
        out.push({ id: d.id, ...(d.data() as any) });
      });
      setRows(out);
      // reset page to first when new data is loaded
      setPage(0);
    } catch (e) {
      console.error("loadHistory error", e);
      setRows([]);
    } finally {
      setLoading(false);
      setLoadedOnce(true);
    }
  }

  // Extract a name and furigana from a single string.
  // Heuristics:
  // - If the string contains parentheses (half/full width) at the end, and the
  //   content inside parentheses contains hiragana/katakana, treat that as furigana.
  // - Otherwise return the original string as name and empty furigana.
  function extractNameAndFurigana(raw: string): {
    name: string;
    furigana: string;
  } {
    if (!raw) return { name: "", furigana: "" };
    try {
      const s = String(raw).trim();
      // match trailing parentheses content
      const m = s.match(/^(.+?)\s*[（(]\s*([^）)]+)\s*[）)]\s*$/);
      if (m) {
        const left = m[1].trim();
        const inside = m[2].trim();
        // if inside contains hiragana or katakana, treat as furigana
        if (/[\u3040-\u30FF]/.test(inside)) {
          return { name: left || "", furigana: inside || "" };
        }
        // sometimes the main part is kana and parentheses contains kanji; swap
        if (/[\u3040-\u30FF]/.test(left) && /[\u4E00-\u9FFF]/.test(inside)) {
          return { name: inside || "", furigana: left || "" };
        }
        // otherwise keep left as name and parentheses as furigana (best-effort)
        return { name: left || "", furigana: inside || "" };
      }
      return { name: s, furigana: "" };
    } catch (e) {
      return { name: raw, furigana: "" };
    }
  }

  // Parse birth date and optional age in parentheses. Handles formats like:
  // "1999年11月12日 (25歳)", "1999年11月12日（25歳）", or just "1999-11-12", etc.
  function extractBirthAndAge(raw: any): { birth: string; age: string } {
    if (!raw && raw !== 0) return { birth: "", age: "" };
    try {
      const s = String(raw).trim();
      // Match trailing parentheses with age
      const m = s.match(/^(.+?)\s*[（(]\s*([0-9]{1,3})\s*歳?\s*[）)]\s*$/);
      if (m) {
        const birthPart = m[1].trim();
        const agePart = m[2].trim();
        return { birth: birthPart, age: agePart };
      }
      // If no parentheses, try to extract an ISO-like date or Japanese date string
      // We'll heuristically accept the whole string as birth
      return { birth: s, age: "" };
    } catch (e) {
      return { birth: String(raw), age: "" };
    }
  }

  function downloadCsv() {
    const headers = [
      "氏名",
      "ふりがな",
      "性別",
      "生年月日",
      "年齢",
      "メールアドレス",
      "電話番号",
      "住所",
      "学校名",
      "応募No",
      "送信日時",
      "送信結果",
    ];

    const esc = (v: any) => {
      if (v === undefined || v === null) return '""';
      let s = String(v);
      s = s.replace(/"/g, '""');
      return `"${s}"`;
    };

    const lines = rows.map((r) => {
      const namePair = extractNameAndFurigana(r.name || r.fullName || "");
      const name = namePair.name;
      const furigana = namePair.furigana;
      // const name already extracted above
      const gender = r.gender || "";
      const birthRaw = r.birth || r.birthdate || "";
      const birthPair = extractBirthAndAge(birthRaw);
      const birth = birthPair.birth;
      const age = birthPair.age;
      const email = r.email || "";
      const tel = r.tel || r.phone || r.mobilenumber || "";
      const addr = r.addr || "";
      const school = r.school || "";
      const oubo = (() => {
        const extracted = r.oubo_no_extracted;
        if (extracted) return extracted;
        const raw = r.oubo_no || "";
        try {
          const m = String(raw).match(/[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+/);
          if (m && m[0]) return m[0];
        } catch (e) {}
        return raw;
      })();

      const sent = (() => {
        const v = r.sentAt || r.sent_at || r.sent_at_seconds || r.sent_at_ts;
        if (v === undefined || v === null) return "";
        try {
          const s = Number(v);
          if (!isFinite(s)) return "";
          const d = new Date(s * 1000);
          const y = d.getFullYear();
          const m = String(d.getMonth() + 1).padStart(2, "0");
          const day = String(d.getDate()).padStart(2, "0");
          const hh = String(d.getHours()).padStart(2, "0");
          const mm = String(d.getMinutes()).padStart(2, "0");
          const ss = String(d.getSeconds()).padStart(2, "0");
          return `${y}/${m}/${day} ${hh}:${mm}:${ss}`;
        } catch (e) {
          return "";
        }
      })();

      const result = (() => {
        const hasStatus =
          r.status !== undefined && r.status !== null && r.status !== "";
        const hasResponse = r.response !== undefined && r.response !== null;
        if (!hasStatus && !hasResponse) return "対象外";
        if (hasStatus) {
          try {
            const s = String(r.status || "");
            if (s === "target_out") return "対象外";
          } catch (e) {}
          return String(r.status);
        }
        try {
          if (typeof r.response === "object" && r.response !== null) {
            const sc =
              r.response.status_code || r.response.status || r.response.code;
            if (sc !== undefined && sc !== null && sc !== "") return String(sc);
          }
          if (typeof r.response === "string" || typeof r.response === "number")
            return String(r.response);
        } catch (e) {}
        return "";
      })();

      return [
        name,
        furigana,
        gender,
        birth,
        age,
        email,
        tel,
        addr,
        school,
        oubo,
        sent,
        result,
      ]
        .map(esc)
        .join(",");
    });

    const csv = "\uFEFF" + headers.map(esc).join(",") + "\n" + lines.join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `history_${new Date()
      .toISOString()
      .slice(0, 19)
      .replace(/[:T]/g, "_")}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div style={{ padding: 28 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <h2 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>HISTORY</h2>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            className="btn"
            onClick={loadHistory}
            disabled={loading}
            style={{ width: "auto" }}
          >
            {loading ? "読み込み中..." : "更新"}
          </button>
          <button
            className="btn btn-gray"
            onClick={() => downloadCsv()}
            disabled={rows.length === 0}
            style={{
              width: "auto",
              display: "inline-flex",
              alignItems: "center",
            }}
          >
            <span className="btn-icon" aria-hidden>
              <svg
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
                aria-hidden
              >
                {/* simple download-into-tray icon */}
                <path
                  d="M12 3v9"
                  stroke="#000"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  fill="none"
                />
                <path
                  d="M8 11l4 4 4-4"
                  stroke="#000"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  fill="none"
                />
                <path
                  d="M4 17a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1H4v1z"
                  stroke="#000"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  fill="none"
                />
              </svg>
            </span>
            <span>CSV出力</span>
          </button>
        </div>
      </div>

      {!loadedOnce && <div>読み込みしています...</div>}

      {loadedOnce && rows.length === 0 && (
        <div style={{ color: "#666" }}>履歴はまだありません。</div>
      )}

      {rows.length > 0 && (
        <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "separate",
              borderSpacing: 0,
              fontFamily:
                "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial",
              fontSize: 14,
              color: "#222",
            }}
          >
            <thead>
              <tr
                style={{
                  background: "#f6f8fa",
                  borderBottom: "1px solid #e6e9ee",
                }}
              >
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                    letterSpacing: ".2px",
                  }}
                >
                  氏名
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  ふりがな
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  性別
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  生年月日
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  年齢
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  メールアドレス
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  電話番号
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  住所
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  学校名
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  応募No
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  送信日時
                </th>
                <th
                  style={{
                    textAlign: "left",
                    padding: "12px 16px",
                    fontWeight: 700,
                  }}
                >
                  送信結果
                </th>
              </tr>
            </thead>
            <tbody>
              {rows
                .slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)
                .map((r, idx) => (
                  <tr
                    key={r.id}
                    style={{
                      borderBottom: "1px solid #eee",
                      background:
                        (page * PAGE_SIZE + idx) % 2 === 0
                          ? "#ffffff"
                          : "#fbfcfd",
                      transition: "background 120ms ease",
                    }}
                  >
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {(() => {
                        const p = extractNameAndFurigana(
                          r.name || r.fullName || ""
                        );
                        return p.name || r.name || r.fullName || "-";
                      })()}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {(() => {
                        const p = extractNameAndFurigana(
                          r.name || r.fullName || ""
                        );
                        return p.furigana || "-";
                      })()}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {r.gender || "-"}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {(() => {
                        const raw = r.birth || r.birthdate || "";
                        const bp = extractBirthAndAge(raw);
                        return bp.birth || "-";
                      })()}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {(() => {
                        const raw = r.birth || r.birthdate || "";
                        const bp = extractBirthAndAge(raw);
                        return bp.age || "-";
                      })()}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {r.email || "-"}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {r.tel || r.phone || r.mobilenumber || "-"}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {r.addr || "-"}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {r.school || "-"}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {(() => {
                        // Prefer explicit extracted field. If absent, try to extract a clean 応募No pattern from r.oubo_no
                        const extracted = r.oubo_no_extracted;
                        if (extracted) return extracted;
                        const raw = r.oubo_no || "";
                        if (!raw) return "-";
                        try {
                          // Match patterns like A2-3616-7244 or 123-456-789 or alphanum groups separated by - (at least one dash)
                          const m = String(raw).match(
                            /[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+/
                          );
                          if (m && m[0]) return m[0];
                        } catch (e) {
                          /* ignore */
                        }
                        // fallback to raw value
                        return raw;
                      })()}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {(() => {
                        const v =
                          r.sentAt ||
                          r.sent_at ||
                          r.sent_at_seconds ||
                          r.sent_at_ts;
                        if (!v && v !== 0) return "-";
                        try {
                          // ensure numeric seconds
                          const s = Number(v);
                          if (!isFinite(s)) return "-";
                          const d = new Date(s * 1000);
                          // JST display
                          const opts: any = { timeZone: "Asia/Tokyo" };
                          const y = d.getFullYear();
                          const m = String(d.getMonth() + 1).padStart(2, "0");
                          const day = String(d.getDate()).padStart(2, "0");
                          const hh = String(d.getHours()).padStart(2, "0");
                          const mm = String(d.getMinutes()).padStart(2, "0");
                          const ss = String(d.getSeconds()).padStart(2, "0");
                          return `${y}/${m}/${day} ${hh}:${mm}:${ss}`;
                        } catch (e) {
                          return "-";
                        }
                      })()}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "top" }}>
                      {(() => {
                        // If not a send target: show 対象外
                        const hasStatus =
                          r.status !== undefined &&
                          r.status !== null &&
                          r.status !== "";
                        const hasResponse =
                          r.response !== undefined && r.response !== null;
                        // If neither status nor response => considered non-target (対象外)
                        if (!hasStatus && !hasResponse) return "対象外";

                        // Prefer numeric/status field if present
                        if (hasStatus) {
                          // If explicitly marked as target_out, show 【対象外】 instead of raw status
                          try {
                            const s = String(r.status || "");
                            if (s === "target_out") return "対象外";
                          } catch (e) {
                            /* ignore */
                          }
                          // If status is a numeric string or number, show as-is
                          return String(r.status);
                        }

                        // Else try response.status_code
                        try {
                          if (
                            typeof r.response === "object" &&
                            r.response !== null
                          ) {
                            const sc =
                              r.response.status_code ||
                              r.response.status ||
                              r.response.code;
                            if (sc !== undefined && sc !== null && sc !== "")
                              return String(sc);
                          }
                          // fallback: if response is primitive, show it
                          if (
                            typeof r.response === "string" ||
                            typeof r.response === "number"
                          )
                            return String(r.response);
                        } catch (e) {
                          // ignore
                        }

                        return "-";
                      })()}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          {/* pagination controls */}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              marginTop: 18,
              gap: 10,
            }}
          >
            <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
              <button
                className="btn"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                style={{ padding: "8px 12px" }}
              >
                前へ
              </button>

              {/* page jump input */}
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <label style={{ color: "#666", fontSize: 13 }}>第</label>
                <input
                  type="number"
                  min={1}
                  value={pageInput}
                  onChange={(e) => setPageInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      const n = Number(pageInput);
                      if (!isFinite(n)) return;
                      const total = Math.max(
                        1,
                        Math.ceil(rows.length / PAGE_SIZE)
                      );
                      const p = Math.max(0, Math.min(total - 1, n - 1));
                      setPage(p);
                    }
                  }}
                  style={{
                    width: 64,
                    padding: "6px 8px",
                    fontSize: 14,
                    borderRadius: 6,
                    border: "1px solid #ccc",
                  }}
                />
                <button
                  className="btn"
                  onClick={() => {
                    const n = Number(pageInput);
                    if (!isFinite(n)) return;
                    const total = Math.max(
                      1,
                      Math.ceil(rows.length / PAGE_SIZE)
                    );
                    const p = Math.max(0, Math.min(total - 1, n - 1));
                    setPage(p);
                  }}
                  style={{
                    padding: "8px 12px",
                    display: "inline-flex",
                    whiteSpace: "nowrap",
                    alignItems: "center",
                  }}
                >
                  移動
                </button>
                {/* removed 'ページ' label for a cleaner layout */}
              </div>

              <button
                className="btn"
                onClick={() =>
                  setPage((p) =>
                    Math.min(p + 1, Math.floor((rows.length - 1) / PAGE_SIZE))
                  )
                }
                disabled={page >= Math.floor((rows.length - 1) / PAGE_SIZE)}
                style={{ padding: "8px 12px" }}
              >
                次へ
              </button>
            </div>

            <div style={{ color: "#666", fontSize: 13 }}>
              合計 {rows.length} 件・全{" "}
              {Math.max(1, Math.ceil(rows.length / PAGE_SIZE))} ページ
            </div>
          </div>
        </div>
      )}

      {serverRows && (
        <div style={{ marginTop: 18 }}>
          <h3>Server fetched rows ({serverRows.length})</h3>
          <pre
            style={{
              maxHeight: 300,
              overflow: "auto",
              background: "#fafafa",
              padding: 8,
            }}
          >
            {JSON.stringify(serverRows, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
