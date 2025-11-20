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
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isSelectMode, setIsSelectMode] = useState(false);

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

      // Read from sms_history collection (unified SMS and mail records)
      const out: any[] = [];

      try {
        const smsCollRef = collection(db, "accounts", uid, "sms_history");
        const smsQ = query(smsCollRef, orderBy("sentAt", "desc"), limit(100));
        const smsSnap = await getDocs(smsQ);
        smsSnap.forEach((d) => {
          out.push({ id: d.id, ...(d.data() as any) });
        });
      } catch (e) {
        console.warn("Failed to load sms_history:", e);
      }

      // Read mail_history for backward compatibility (old mail records only)
      try {
        const mailCollRef = collection(db, "accounts", uid, "mail_history");
        const mailQ = query(mailCollRef, orderBy("sentAt", "desc"), limit(50));
        const mailSnap = await getDocs(mailQ);
        mailSnap.forEach((d) => {
          const data = d.data() as any;
          // Add (M) suffix to status if not already present for old mail records
          if (
            data.status &&
            !data.status.includes("(M)") &&
            !data.status.includes("（M）")
          ) {
            data.status = data.status.includes("送信済")
              ? "送信済（M）"
              : data.status.includes("送信失敗")
              ? "送信失敗（M）"
              : `${data.status}（M）`;
          }
          out.push({ id: d.id, source: "mail_history", ...data });
        });
      } catch (e) {
        console.warn("Failed to load mail_history:", e);
      }

      // Sort all records by sentAt descending and take top 100
      out.sort((a, b) => {
        const aTime = a.sentAt || 0;
        const bTime = b.sentAt || 0;
        return bTime - aTime;
      });

      setRows(out.slice(0, 100));
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
    // 如果不在选择模式,进入选择模式
    if (!isSelectMode) {
      setIsSelectMode(true);
      return;
    }

    // 在选择模式下,执行下载
    const selectedRows = rows.filter((r) => selectedIds.has(r.id));

    if (selectedRows.length === 0) {
      alert("ダウンロードする項目を選択してください。");
      return;
    }

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

    const lines = selectedRows.map((r) => {
      const namePair = extractNameAndFurigana(r.name || r.fullName || "");
      // 姓名空格统一为半角
      const name = namePair.name.replace(/[　]+/g, " ").replace(/ +/g, " ");
      // ふりがな空格统一为半角
      const furigana = namePair.furigana
        .replace(/[　]+/g, " ")
        .replace(/ +/g, " ");
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
          r.status !== undefined &&
          r.status !== null &&
          String(r.status).trim() !== "";
        const hasResponse = r.response !== undefined && r.response !== null;

        // If neither status nor response -> target out
        if (!hasStatus && !hasResponse) return "対象外";

        // If status already contains a detailed suffix (（M） or （S）) prefer to show it verbatim
        try {
          const s = String(r.status || "").trim();
          if (
            s &&
            (s.indexOf("（M）") >= 0 ||
              s.indexOf("(M)") >= 0 ||
              s.indexOf("（S）") >= 0 ||
              s.indexOf("(S)") >= 0 ||
              s.indexOf("M+S") >= 0 ||
              s.indexOf("M+S") >= 0)
          ) {
            return s; // show detailed status as-is (e.g. 送信済（M）/送信済（S）/送信済（M+S）)
          }
          // backward-compat: existing coarse logic
          if (
            s === "送信済" ||
            s.startsWith("送信済") ||
            (s.indexOf("送信") >= 0 && s.indexOf("済") >= 0)
          )
            return "送信済";
          if (s === "target_out") return "対象外";
        } catch (e) {}

        // Inspect response for success/failed
        try {
          if (typeof r.response === "object" && r.response !== null) {
            const sc =
              r.response.status_code ||
              r.response.status ||
              r.response.code ||
              r.response.codeNumber;
            const scNum = Number(sc);
            if (!Number.isNaN(scNum) && scNum >= 200 && scNum < 300)
              return "送信済";
            if (!Number.isNaN(scNum)) return `送信失敗${scNum}`;
            const asStr = JSON.stringify(r.response || "");
            if (asStr.indexOf("200") >= 0) return "送信済";
            return `送信失敗${asStr}`;
          }
          if (
            typeof r.response === "string" ||
            typeof r.response === "number"
          ) {
            const scNum = Number(r.response);
            if (!Number.isNaN(scNum) && scNum >= 200 && scNum < 300)
              return "送信済";
            const s = String(r.response);
            if (s.indexOf("200") >= 0) return "送信済";
            return `送信失敗${s}`;
          }
        } catch (e) {}

        // Fallback: if status existed but didn't indicate sent, return it; otherwise treat as failed
        if (hasStatus) return String(r.status);
        return "送信失敗";
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

  // 切换单个选择
  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(id)) {
        newSet.delete(id);
      } else {
        newSet.add(id);
      }
      return newSet;
    });
  };

  // 全选/取消全选当前页
  const toggleSelectAll = () => {
    const currentPageRows = rows.slice(
      page * PAGE_SIZE,
      (page + 1) * PAGE_SIZE
    );
    const currentPageIds = currentPageRows.map((r) => r.id);
    const allSelected = currentPageIds.every((id) => selectedIds.has(id));

    setSelectedIds((prev) => {
      const newSet = new Set(prev);
      if (allSelected) {
        // 取消全选当前页
        currentPageIds.forEach((id) => newSet.delete(id));
      } else {
        // 全选当前页
        currentPageIds.forEach((id) => newSet.add(id));
      }
      return newSet;
    });
  };

  // 检查当前页是否全选
  const isAllSelected = () => {
    const currentPageRows = rows.slice(
      page * PAGE_SIZE,
      (page + 1) * PAGE_SIZE
    );
    if (currentPageRows.length === 0) return false;
    return currentPageRows.every((r) => selectedIds.has(r.id));
  };

  // 取消选择模式
  const cancelSelectMode = () => {
    setIsSelectMode(false);
    setSelectedIds(new Set());
  };

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
            disabled={
              rows.length === 0 || (isSelectMode && selectedIds.size === 0)
            }
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
            <span>
              {isSelectMode
                ? `ダウンロード${
                    selectedIds.size > 0 ? ` (${selectedIds.size})` : ""
                  }`
                : "CSV出力"}
            </span>
          </button>
          {isSelectMode && (
            <button
              className="btn"
              onClick={cancelSelectMode}
              style={{ width: "auto" }}
            >
              キャンセル
            </button>
          )}
        </div>
      </div>

      {!loadedOnce && <div>読み込みしています...</div>}

      {loadedOnce && rows.length === 0 && (
        <div style={{ color: "#666" }}>履歴はまだありません。</div>
      )}

      {rows.length > 0 && (
        <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
          <table
            className="history-table"
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
              <tr>
                {isSelectMode && (
                  <th style={{ textAlign: "center", width: "40px" }}>
                    <input
                      type="checkbox"
                      checked={isAllSelected()}
                      onChange={toggleSelectAll}
                      style={{ cursor: "pointer" }}
                    />
                  </th>
                )}
                <th style={{ textAlign: "left" }}>氏名</th>
                <th style={{ textAlign: "left" }}>ふりがな</th>
                <th style={{ textAlign: "left" }}>性別</th>
                <th style={{ textAlign: "left" }}>生年月日</th>
                <th style={{ textAlign: "left" }}>年齢</th>
                <th style={{ textAlign: "left" }}>メールアドレス</th>
                <th style={{ textAlign: "left" }}>電話番号</th>
                <th style={{ textAlign: "left" }}>住所</th>
                <th style={{ textAlign: "left" }}>応募No</th>
                <th style={{ textAlign: "left" }}>送信日時</th>
                <th style={{ textAlign: "left" }}>送信結果</th>
              </tr>
            </thead>
            <tbody>
              {(() => {
                const slicedRows = rows.slice(
                  page * PAGE_SIZE,
                  page * PAGE_SIZE + PAGE_SIZE
                );
                return slicedRows.map((r, idx) => (
                  <tr
                    key={r.id}
                    className={"history-row"}
                    onClick={() => isSelectMode && toggleSelect(r.id)}
                    style={{ cursor: isSelectMode ? "pointer" : "default" }}
                  >
                    {isSelectMode && (
                      <td
                        className="history-cell"
                        style={{ textAlign: "center" }}
                      >
                        <input
                          type="checkbox"
                          checked={selectedIds.has(r.id)}
                          onChange={() => {}}
                          style={{ cursor: "pointer", pointerEvents: "none" }}
                        />
                      </td>
                    )}
                    <td className="history-cell">
                      {(() => {
                        const p = extractNameAndFurigana(
                          r.name || r.fullName || ""
                        );
                        // 姓名空格统一为半角
                        return (p.name || r.name || r.fullName || "-")
                          .replace(/[　]+/g, " ")
                          .replace(/ +/g, " ");
                      })()}
                    </td>
                    <td className="history-cell">
                      {(() => {
                        const p = extractNameAndFurigana(
                          r.name || r.fullName || ""
                        );
                        // ふりがな空格统一为半角
                        return (p.furigana || "-")
                          .replace(/[　]+/g, " ")
                          .replace(/ +/g, " ");
                      })()}
                    </td>
                    <td className="history-cell">{r.gender || "-"}</td>
                    <td className="history-cell">
                      {(() => {
                        const raw = r.birth || r.birthdate || "";
                        const bp = extractBirthAndAge(raw);
                        return bp.birth || "-";
                      })()}
                    </td>
                    <td className="history-cell">
                      {(() => {
                        const raw = r.birth || r.birthdate || "";
                        const bp = extractBirthAndAge(raw);
                        return bp.age || "-";
                      })()}
                    </td>
                    <td className="history-cell">{r.email || "-"}</td>
                    <td className="history-cell">
                      {r.tel || r.phone || r.mobilenumber || "-"}
                    </td>
                    <td className="history-cell">{r.addr || "-"}</td>
                    <td className="history-cell">
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
                    <td className="history-cell">
                      {/* 表格美化样式 */}
                      <style>{`
            .history-table th {
              background: #f6f8fa;
              font-weight: 700;
              font-size: 15px;
              padding: 8px 10px;
              border-bottom: 2px solid #e6e9ee;
              color: #222;
            }
            .history-table td.history-cell {
              padding: 8px 10px;
              border-bottom: 1px solid #e6e9ee;
              font-size: 14px;
              color: #222;
              background: #fff;
              vertical-align: top;
              transition: background 0.2s;
            }
            .history-table tr.history-row:nth-child(even) td.history-cell {
              background: #f7fafd;
            }
            .history-table tr.history-row:hover td.history-cell {
              background: #e3f2fd;
            }
            .history-table {
              border-radius: 8px;
              overflow: hidden;
              box-shadow: 0 2px 12px rgba(16,24,32,0.06);
              border: 1px solid #e6e9ee;
            }
          `}</style>
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
                    <td className="history-cell">
                      {(() => {
                        // 送信結果内容高亮
                        const getStatusClass = (val) => {
                          if (!val || val === "-") return "result-unknown";
                          if (val.includes("送信済")) return "result-success";
                          if (val.includes("失敗")) return "result-fail";
                          if (val.includes("対象外") || val === "target_out")
                            return "result-out";
                          return "result-unknown";
                        };
                        // 原有逻辑
                        const hasStatus =
                          r.status !== undefined &&
                          r.status !== null &&
                          r.status !== "";
                        const hasResponse =
                          r.response !== undefined && r.response !== null;
                        let val = "-";
                        if (!hasStatus && !hasResponse) val = "対象外";
                        else if (hasStatus) {
                          try {
                            const s = String(r.status || "");
                            if (s === "target_out") val = "対象外";
                            else val = s;
                          } catch (e) {
                            val = String(r.status);
                          }
                        } else {
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
                                val = String(sc);
                            } else if (
                              typeof r.response === "string" ||
                              typeof r.response === "number"
                            ) {
                              val = String(r.response);
                            }
                          } catch (e) {}
                        }
                        return (
                          <span className={getStatusClass(val)}>{val}</span>
                        );
                      })()}
                    </td>
                    <style>{`
            .history-table th {
              background: #f6f8fa;
              font-weight: 700;
              font-size: 15px;
              padding: 8px 10px;
              border-bottom: 2px solid #e6e9ee;
              color: #222;
            }
            .history-table td.history-cell {
              padding: 8px 10px;
              border-bottom: 1px solid #e6e9ee;
              font-size: 14px;
              color: #222;
              background: #fff;
              vertical-align: top;
              transition: background 0.2s;
            }
            .history-table tr.history-row:nth-child(even) td.history-cell {
              background: #f7fafd;
            }
            .history-table tr.history-row:hover td.history-cell {
              background: #e3f2fd;
            }
            .history-table {
              border-radius: 8px;
              overflow: hidden;
              box-shadow: 0 2px 12px rgba(16,24,32,0.06);
              border: 1px solid #e6e9ee;
            }
            /* 送信結果高亮样式 */
            .result-success {
              color: #219653;
              font-weight: 700;
              background: #eafbe7;
              border-radius: 4px;
              padding: 2px 6px;
              display: inline-block;
            }
            .result-fail {
              color: #d32f2f;
              font-weight: 700;
              background: #fdeaea;
              border-radius: 4px;
              padding: 2px 6px;
              display: inline-block;
            }
            .result-out {
              color: #888;
              font-weight: 600;
              background: #f3f3f3;
              border-radius: 4px;
              padding: 2px 6px;
              display: inline-block;
            }
            .result-unknown {
              color: #222;
              font-weight: 400;
              background: #fff;
              border-radius: 4px;
              padding: 2px 6px;
              display: inline-block;
            }
          `}</style>
                  </tr>
                ));
              })()}
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
