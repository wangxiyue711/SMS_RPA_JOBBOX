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

type EngageAccountRow = {
  account_name: string;
  engage_id: string;
  engage_password: string;
};

type SiteType = "jobbox" | "engage";

export default function RPASettingsPage() {
  const [siteType, setSiteType] = useState<SiteType>("jobbox");
  const [formData, setFormData] = useState<AccountRow>({
    account_name: "",
    jobbox_id: "",
    jobbox_password: "",
  });
  const [engageFormData, setEngageFormData] = useState<EngageAccountRow>({
    account_name: "",
    engage_id: "",
    engage_password: "",
  });
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState<Array<any>>([]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  // For compatibility with existing code
  const rows = [formData];
  const showPasswords = [showPassword];

  const updateRow = (idx: number, field: keyof AccountRow, value: string) => {
    if (idx === 0) {
      setFormData((prev) => ({
        ...prev,
        [field]: value,
      }));
    }
  };

  const toggleShowPassword = (idx: number) => {
    if (idx === 0) {
      setShowPassword(!showPassword);
    }
  };

  const loadSaved = async () => {
    try {
      const auth = getClientAuth();
      if (!auth || !auth.currentUser) return;
      const uid = auth.currentUser.uid;
      const db = getFirestore();
      const collectionName =
        siteType === "jobbox" ? "jobbox_accounts" : "engage_accounts";
      console.log(
        `Loading accounts from: ${collectionName}, siteType: ${siteType}`
      );
      const snap = await getDocs(
        collection(db, "accounts", uid, collectionName)
      );
      const list: any[] = [];
      snap.forEach((d) => {
        const passwordField =
          siteType === "jobbox"
            ? "jobbox_password_hidden"
            : "engage_password_hidden";
        list.push({ id: d.id, ...d.data(), [passwordField]: true });
      });
      console.log(`Loaded ${list.length} accounts:`, list);
      setSaved(list);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    // 立即清空列表,然后重新加载
    setSaved([]);
    loadSaved();
  }, [siteType]);

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
      console.log("Saving accounts for uid=", uid, "siteType=", siteType);
      const db = getFirestore();

      if (siteType === "jobbox") {
        const valid = rows.filter(
          (r) => r.account_name && r.jobbox_id && r.jobbox_password
        );
        if (valid.length === 0) throw new Error("入力してください");
        await Promise.all(
          valid.map((r) =>
            addDoc(collection(db, "accounts", uid, "jobbox_accounts"), r)
          )
        );
        setFormData({ account_name: "", jobbox_id: "", jobbox_password: "" });
      } else {
        // engage
        if (
          !engageFormData.account_name ||
          !engageFormData.engage_id ||
          !engageFormData.engage_password
        ) {
          throw new Error("入力してください");
        }
        await addDoc(
          collection(db, "accounts", uid, "engage_accounts"),
          engageFormData
        );
        setEngageFormData({
          account_name: "",
          engage_id: "",
          engage_password: "",
        });
      }

      await loadSaved();
      setSuccess("✅ 保存しました！");
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
      const collectionName =
        siteType === "jobbox" ? "jobbox_accounts" : "engage_accounts";
      await deleteDoc(doc(db, "accounts", uid, collectionName, id));
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
      <p style={{ marginBottom: 24 }}>
        RoMeALLで使用する求人サイトアカウントを登録 / 管理することができます。
      </p>

      {/* Tab UI for Site Selection */}
      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 24,
          borderBottom: "2px solid #e5e7eb",
        }}
      >
        <button
          type="button"
          onClick={() => setSiteType("jobbox")}
          style={{
            padding: "12px 24px",
            fontWeight: 600,
            background: "transparent",
            border: "none",
            borderBottom:
              siteType === "jobbox"
                ? "3px solid #36bdccff"
                : "3px solid transparent",
            color: siteType === "jobbox" ? "#36bdccff" : "#6b7280",
            cursor: "pointer",
            transition: "all 0.2s",
          }}
        >
          求人ボックス
        </button>
        <button
          type="button"
          onClick={() => setSiteType("engage")}
          style={{
            padding: "12px 24px",
            fontWeight: 600,
            background: "transparent",
            border: "none",
            borderBottom:
              siteType === "engage"
                ? "3px solid #36bdccff"
                : "3px solid transparent",
            color: siteType === "engage" ? "#36bdccff" : "#6b7280",
            cursor: "pointer",
            transition: "all 0.2s",
          }}
        >
          エンゲージ
        </button>
      </div>

      {/* 新規アカウント登録ブロック */}
      <div
        style={{
          background: "var(--card)",
          border: "1px solid rgba(48, 48, 48, 0.08)",
          borderRadius: 12,
          padding: 24,
          marginBottom: 32,
        }}
      >
        <form onSubmit={handleSave} autoComplete="off">
          {/* Hidden fields to trap browser autofill (do not remove) */}
          <div
            style={{
              position: "absolute",
              left: -9999,
              top: -9999,
              opacity: 0,
            }}
            aria-hidden
          >
            <input name="fake-username" type="text" autoComplete="username" />
            <input
              name="fake-password"
              type="password"
              autoComplete="current-password"
            />
          </div>

          <div style={{ display: "grid", gap: 16, marginBottom: 20 }}>
            <div>
              <label
                style={{
                  display: "block",
                  marginBottom: 6,
                  fontSize: 14,
                  fontWeight: 500,
                }}
              >
                {siteType === "jobbox"
                  ? "求人ボックスアカウント名"
                  : "エンゲージアカウント名"}
              </label>
              <input
                name={
                  siteType === "jobbox"
                    ? "jobbox_account_name"
                    : "engage_account_name"
                }
                autoComplete="off"
                value={
                  siteType === "jobbox"
                    ? rows[0]?.account_name || ""
                    : engageFormData.account_name || ""
                }
                onChange={(e) => {
                  if (siteType === "jobbox") {
                    updateRow(0, "account_name", e.target.value);
                  } else {
                    setEngageFormData({
                      ...engageFormData,
                      account_name: e.target.value,
                    });
                  }
                }}
                placeholder="xxx株式会社"
                required
                className="input"
                style={{ width: "100%", boxSizing: "border-box" }}
              />
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 16,
              }}
            >
              <div>
                <label
                  style={{
                    display: "block",
                    marginBottom: 6,
                    fontSize: 14,
                    fontWeight: 500,
                  }}
                >
                  メールアドレス
                </label>
                <input
                  name={siteType === "jobbox" ? "jobbox_id" : "engage_id"}
                  autoComplete="off"
                  value={
                    siteType === "jobbox"
                      ? rows[0]?.jobbox_id || ""
                      : engageFormData.engage_id || ""
                  }
                  onChange={(e) => {
                    if (siteType === "jobbox") {
                      updateRow(0, "jobbox_id", e.target.value);
                    } else {
                      setEngageFormData({
                        ...engageFormData,
                        engage_id: e.target.value,
                      });
                    }
                  }}
                  placeholder="sample@sample-job.biz"
                  required
                  className="input"
                  style={{ width: "100%", boxSizing: "border-box" }}
                />
              </div>

              <div>
                <label
                  style={{
                    display: "block",
                    marginBottom: 6,
                    fontSize: 14,
                    fontWeight: 500,
                  }}
                >
                  パスワード
                </label>
                <div className="input-with-icon">
                  <input
                    name={
                      siteType === "jobbox"
                        ? "jobbox_password"
                        : "engage_password"
                    }
                    autoComplete="new-password"
                    type={showPasswords[0] ? "text" : "password"}
                    value={
                      siteType === "jobbox"
                        ? rows[0]?.jobbox_password || ""
                        : engageFormData.engage_password || ""
                    }
                    onChange={(e) => {
                      if (siteType === "jobbox") {
                        updateRow(0, "jobbox_password", e.target.value);
                      } else {
                        setEngageFormData({
                          ...engageFormData,
                          engage_password: e.target.value,
                        });
                      }
                    }}
                    placeholder="パスワードを入力してください"
                    required
                    className="input"
                    style={{ width: "100%", boxSizing: "border-box" }}
                  />
                  <button
                    type="button"
                    className="password-toggle"
                    onClick={() => toggleShowPassword(0)}
                    aria-label={showPasswords[0] ? "隠す" : "表示"}
                  >
                    {showPasswords[0] ? (
                      <svg
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                        <line x1="1" y1="1" x2="23" y2="23" />
                      </svg>
                    ) : (
                      <svg
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>
          <button className="btn" type="submit" disabled={loading}>
            {loading ? "保存中..." : "保存"}
          </button>
          {error && <div style={{ color: "red", marginTop: 8 }}>{error}</div>}
          {success && (
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                color: "#28a745",
                marginTop: 8,
                fontWeight: 700,
              }}
            >
              {success}
            </div>
          )}
        </form>
      </div>

      <h3 style={{ marginTop: 28, marginBottom: 12 }}>保存済みアカウント</h3>
      <div
        style={{
          background: "var(--card)",
          border: "1px solid rgba(48,48,48,0.08)",
          borderRadius: 12,
          padding: 20,
          marginBottom: 24,
        }}
      >
        {saved.length === 0 ? (
          <div>アカウントはまだ保存されていません。</div>
        ) : (
          <ul
            className="saved-list"
            style={{
              listStyle: "none",
              padding: 0,
              margin: 0,
              display: "grid",
              gap: 12,
            }}
          >
            {saved.map((s, i) => (
              <li
                key={s.id}
                onMouseEnter={() => setHoveredIndex(i)}
                onMouseLeave={() => setHoveredIndex(null)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  background:
                    hoveredIndex === i
                      ? "#eef6fb"
                      : i % 2 === 0
                      ? "#ffffff"
                      : "#fbfbfc",
                  padding: 12,
                  borderRadius: 8,
                  transition: "background 120ms ease",
                }}
              >
                <div style={{ flex: "1 1 auto", minWidth: 0 }}>
                  <div
                    style={{
                      fontWeight: 700,
                      color: "var(--text, #111)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {s.account_name}
                  </div>
                  <div
                    style={{
                      color: "var(--muted, #666)",
                      fontSize: 13,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {siteType === "jobbox"
                      ? (s as any).jobbox_id
                      : (s as any).engage_id}
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
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <span style={{ fontFamily: "monospace" }}>
                      {siteType === "jobbox"
                        ? (s as any).jobbox_password_hidden
                          ? "●●●●●●"
                          : (s as any).jobbox_password
                        : (s as any).engage_password_hidden
                        ? "●●●●●●"
                        : (s as any).engage_password}
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setSaved((prev) =>
                          prev.map((it, idx) => {
                            if (idx !== i) return it;
                            if (siteType === "jobbox") {
                              return {
                                ...it,
                                jobbox_password_hidden: !(it as any)
                                  .jobbox_password_hidden,
                              };
                            } else {
                              return {
                                ...it,
                                engage_password_hidden: !(it as any)
                                  .engage_password_hidden,
                              };
                            }
                          })
                        )
                      }
                      aria-label={
                        siteType === "jobbox"
                          ? (s as any).jobbox_password_hidden
                            ? "表示"
                            : "隠す"
                          : (s as any).engage_password_hidden
                          ? "表示"
                          : "隠す"
                      }
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
                      {(
                        siteType === "jobbox"
                          ? (s as any).jobbox_password_hidden
                          : (s as any).engage_password_hidden
                      ) ? (
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
                          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                          <circle cx="12" cy="12" r="3" />
                          <line x1="1" y1="1" x2="23" y2="23" />
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
      </div>
      {/* success message moved to form area */}
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
            background: "rgba(0,0,0,0.35)",
            zIndex: 9999,
            padding: 20,
          }}
          onClick={() => {
            setConfirmOpen(false);
            setConfirmId(null);
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#efefef",
              padding: 20,
              borderRadius: 10,
              minWidth: 320,
              maxWidth: 520,
              width: "100%",
              boxShadow: "0 12px 28px rgba(0,0,0,0.15)",
            }}
          >
            <div style={{ marginBottom: 8, fontWeight: 800, fontSize: 16 }}>
              確認
            </div>
            <div style={{ marginBottom: 20, color: "#222" }}>
              このアカウントを削除してもよろしいですか？
            </div>

            <div style={{ display: "flex", gap: 12 }}>
              <button
                onClick={() => {
                  setConfirmOpen(false);
                  setConfirmId(null);
                }}
                style={{
                  flex: 1,
                  background: "#fff",
                  border: "1px solid rgba(0,0,0,0.12)",
                  color: "#111",
                  padding: "10px 12px",
                  borderRadius: 8,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                キャンセル
              </button>

              <button
                onClick={async () => {
                  if (confirmId) await handleDelete(confirmId);
                  setConfirmOpen(false);
                  setConfirmId(null);
                }}
                style={{
                  flex: 1,
                  background: "#2e2e2e",
                  border: "none",
                  color: "#fff",
                  padding: "10px 12px",
                  borderRadius: 8,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
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
