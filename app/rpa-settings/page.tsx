"use client";

import React, { useEffect, useState } from "react";
import { getClientAuth } from "../../lib/firebaseClient";
import {
  getFirestore,
  collection,
  addDoc,
  getDocs,
  deleteDoc,
  doc,
} from "firebase/firestore";
import { onAuthStateChanged } from "firebase/auth";

type AccountRow = {
  account_name: string;
  jobbox_id: string;
  jobbox_password: string;
};

export default function RPASettingsPage() {
  const [rows, setRows] = useState<AccountRow[]>([
    { account_name: "", jobbox_id: "", jobbox_password: "" },
  ]);
  const [showPasswords, setShowPasswords] = useState<boolean[]>([false]);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState<Array<any>>([]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const addRow = () =>
    setRows((r) => [
      ...r,
      { account_name: "", jobbox_id: "", jobbox_password: "" },
    ]);
  const removeRow = (idx: number) =>
    setRows((r) => r.filter((_, i) => i !== idx));
  const updateRow = (idx: number, field: keyof AccountRow, value: string) => {
    const copy = [...rows];
    copy[idx][field] = value;
    setRows(copy);
  };

  const toggleShowPassword = (idx: number) => {
    setShowPasswords((s) => {
      const copy = [...s];
      if (idx >= copy.length) {
        // extend to match rows
        while (copy.length <= idx) copy.push(false);
      }
      copy[idx] = !copy[idx];
      return copy;
    });
  };

  const loadSaved = async () => {
    try {
      const auth = getClientAuth();
      if (!auth || !auth.currentUser) return;
      const uid = auth.currentUser.uid;
      const db = getFirestore();
      const snap = await getDocs(
        collection(db, "accounts", uid, "jobbox_accounts")
      );
      const list: any[] = [];
      snap.forEach((d) =>
        list.push({ id: d.id, ...d.data(), jobbox_password_hidden: true })
      );
      setSaved(list);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    loadSaved();
  }, []);

  // wait for auth to be ready (useful if auth is initializing)
  const waitForAuthReady = async (timeout = 4000) => {
    const auth = getClientAuth();
    if (!auth) return null;
    if (auth.currentUser) return auth.currentUser;
    return new Promise((resolve) => {
      const unsub = onAuthStateChanged(auth, (user) => {
        if (user) {
          try {
            unsub();
          } catch {}
          resolve(user);
        }
      });
      setTimeout(() => {
        try {
          unsub();
        } catch {}
        resolve(null);
      }, timeout);
    });
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const authUser: any = await waitForAuthReady();
      if (!authUser) throw new Error("ログインしてください");
      const uid = authUser.uid;
      console.log("Saving accounts for uid=", uid);
      const db = getFirestore();
      const valid = rows.filter(
        (r) => r.account_name && r.jobbox_id && r.jobbox_password
      );
      if (valid.length === 0) throw new Error("入力してください");
      await Promise.all(
        valid.map((r) =>
          addDoc(collection(db, "accounts", uid, "jobbox_accounts"), r)
        )
      );
      setRows([{ account_name: "", jobbox_id: "", jobbox_password: "" }]);
      await loadSaved();
      setSuccess("保存しました");
      setTimeout(() => setSuccess(""), 3000);
    } catch (err: any) {
      console.error("save error", err);
      const code = err && err.code ? err.code : "";
      setError((code ? `${code}: ` : "") + (err?.message || "エラー"));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      const auth = getClientAuth();
      if (!auth || !auth.currentUser) return;
      const uid = auth.currentUser.uid;
      const db = getFirestore();
      await deleteDoc(doc(db, "accounts", uid, "jobbox_accounts", id));
      await loadSaved();
    } catch (e: any) {
      console.error("delete error", e);
    }
  };

  return (
    <div style={{ padding: 28 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12 }}>
        アカウント設定
      </h2>
      <p style={{ marginBottom: 16 }}>
        RPAに使用する求人ボックスアカウントを追加できます。保存後、RPA実行時にクラウドから読み込みます。
      </p>

      <form onSubmit={handleSave}>
        <table
          style={{ width: "100%", marginBottom: 12, tableLayout: "fixed" }}
        >
          <colgroup>
            <col style={{ width: "28%" }} />
            <col style={{ width: "32%" }} />
            <col style={{ width: "30%" }} />
            <col style={{ width: "10%" }} />
          </colgroup>
          <thead>
            <tr>
              <th>アカウント名</th>
              <th>メール</th>
              <th>パスワード</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, idx) => (
              <tr key={idx}>
                <td>
                  <input
                    value={r.account_name}
                    onChange={(e) =>
                      updateRow(idx, "account_name", e.target.value)
                    }
                    required
                    style={{ width: "100%", boxSizing: "border-box" }}
                  />
                </td>
                <td>
                  <input
                    value={r.jobbox_id}
                    onChange={(e) =>
                      updateRow(idx, "jobbox_id", e.target.value)
                    }
                    required
                    style={{ width: "100%", boxSizing: "border-box" }}
                  />
                </td>
                <td>
                  <div style={{ position: "relative" }}>
                    <input
                      type={showPasswords[idx] ? "text" : "password"}
                      value={r.jobbox_password}
                      onChange={(e) =>
                        updateRow(idx, "jobbox_password", e.target.value)
                      }
                      required
                      style={{
                        width: "100%",
                        paddingRight: 44,
                        boxSizing: "border-box",
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => toggleShowPassword(idx)}
                      aria-label={showPasswords[idx] ? "隠す" : "表示"}
                      style={{
                        position: "absolute",
                        right: 6,
                        top: "50%",
                        transform: "translateY(-50%)",
                        border: "none",
                        background: "transparent",
                        cursor: "pointer",
                        padding: 6,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        zIndex: 3,
                      }}
                    >
                      {showPasswords[idx] ? (
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="18"
                          height="18"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden
                        >
                          <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-5 0-9.27-3-11-7 1.11-2.45 2.98-4.44 5.23-5.66" />
                          <path d="M1 1l22 22" />
                        </svg>
                      ) : (
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="18"
                          height="18"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          aria-hidden
                        >
                          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
                          <circle cx="12" cy="12" r="3" />
                        </svg>
                      )}
                    </button>
                  </div>
                </td>
                <td style={{ textAlign: "center" }}>
                  <button
                    type="button"
                    onClick={() => removeRow(idx)}
                    disabled={rows.length === 1}
                  >
                    削除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ marginBottom: 12 }}>
          <button type="button" onClick={addRow}>
            行を追加
          </button>
        </div>
        <button className="btn" type="submit" disabled={loading}>
          {loading ? "保存中..." : "保存"}
        </button>
        {error && <div style={{ color: "red", marginTop: 8 }}>{error}</div>}
      </form>

      <h3 style={{ marginTop: 28, marginBottom: 12 }}>保存済みアカウント</h3>
      {saved.length === 0 ? (
        <div>アカウントはまだ保存されていません。</div>
      ) : (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "grid",
            gap: 8,
          }}
        >
          {saved.map((s, i) => (
            <li
              key={s.id}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                background: "rgba(255,255,255,0.03)",
                border: "1px solid rgba(255,255,255,0.06)",
                padding: 12,
                borderRadius: 8,
              }}
            >
              <div style={{ flex: "1 1 auto", minWidth: 0 }}>
                <div
                  style={{
                    fontWeight: 700,
                    color: "var(--text, #fff)",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {s.account_name}
                </div>
                <div
                  style={{
                    color: "var(--muted, #aaa)",
                    fontSize: 13,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {s.jobbox_id}
                </div>
              </div>

              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  marginLeft: 12,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontFamily: "monospace" }}>
                    {s.jobbox_password_hidden ? "●●●●●●" : s.jobbox_password}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setSaved((prev) =>
                        prev.map((it, idx) =>
                          idx === i
                            ? {
                                ...it,
                                jobbox_password_hidden:
                                  !it.jobbox_password_hidden,
                              }
                            : it
                        )
                      )
                    }
                    aria-label={s.jobbox_password_hidden ? "表示" : "隠す"}
                    style={{
                      border: "none",
                      background: "transparent",
                      cursor: "pointer",
                      padding: 6,
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      width: 32,
                      height: 32,
                      lineHeight: 0,
                    }}
                  >
                    {s.jobbox_password_hidden ? (
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="18"
                        height="18"
                        style={{ display: "block" }}
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden
                      >
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    ) : (
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="18"
                        height="18"
                        style={{ display: "block" }}
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden
                      >
                        <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-5 0-9.27-3-11-7 1.11-2.45 2.98-4.44 5.23-5.66" />
                        <path d="M1 1l22 22" />
                      </svg>
                    )}
                  </button>
                </div>

                <div>
                  <button
                    onClick={() => {
                      setConfirmId(s.id);
                      setConfirmOpen(true);
                    }}
                    aria-label="削除"
                    style={{
                      border: "none",
                      background: "transparent",
                      cursor: "pointer",
                      padding: 6,
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "var(--shade-1)",
                      width: 32,
                      height: 32,
                      lineHeight: 0,
                    }}
                  >
                    <svg
                      width="18"
                      height="18"
                      viewBox="0 0 24 24"
                      fill="none"
                      xmlns="http://www.w3.org/2000/svg"
                      style={{ display: "block" }}
                    >
                      <path
                        d="M18 6L6 18"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                      <path
                        d="M6 6L18 18"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {success && (
        <div
          className="msg"
          style={{ color: "var(--accent)", marginTop: 12, fontWeight: 700 }}
        >
          {success}
        </div>
      )}
      {confirmOpen && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: "fixed",
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(0,0,0,0.4)",
            zIndex: 9999,
          }}
          onClick={() => {
            setConfirmOpen(false);
            setConfirmId(null);
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "var(--bg, #0b0b0b)",
              padding: 18,
              borderRadius: 8,
              minWidth: 320,
              boxShadow: "0 8px 24px rgba(0,0,0,0.6)",
            }}
          >
            <div style={{ marginBottom: 12, fontWeight: 700 }}>確認</div>
            <div style={{ marginBottom: 18 }}>
              このアカウントを削除してもよろしいですか？
            </div>
            <div
              style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}
            >
              <button
                onClick={() => {
                  setConfirmOpen(false);
                  setConfirmId(null);
                }}
                style={{ padding: "8px 12px" }}
              >
                キャンセル
              </button>
              <button
                onClick={async () => {
                  if (confirmId) await handleDelete(confirmId);
                  setConfirmOpen(false);
                  setConfirmId(null);
                }}
                className="btn"
                style={{ padding: "8px 12px" }}
              >
                削除
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
