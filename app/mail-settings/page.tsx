"use client";

import React, { useEffect, useState } from "react";
import { getClientAuth } from "../../lib/firebaseClient";
import {
  getFirestore,
  doc,
  getDoc,
  setDoc,
  deleteDoc,
} from "firebase/firestore";

async function waitForAuthReady(timeout = 3000): Promise<any | null> {
  const auth = getClientAuth();
  if (!auth) return null;
  if (auth.currentUser) return auth.currentUser;
  return new Promise((resolve) => {
    const unsub = auth.onAuthStateChanged((u) => {
      unsub();
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

type SiteType = "jobbox" | "engage";

export default function MailSettingsPage() {
  const [siteType, setSiteType] = useState<SiteType>("jobbox");
  const [email, setEmail] = useState("");
  const [appPass, setAppPass] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showPass, setShowPass] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");
  const [fieldError, setFieldError] = useState<{
    field: string;
    msg: string;
  } | null>(null);

  useEffect(() => {
    loadSetting();
  }, [siteType]);

  async function loadSetting() {
    const user = await waitForAuthReady();
    if (!user) return;
    const db = getFirestore();
    const uid = (user as any).uid;
    const collectionName =
      siteType === "jobbox" ? "mail_settings" : "engage_mail_settings";
    const docRef = doc(db, "accounts", uid, collectionName, "settings");
    const snap = await getDoc(docRef);
    if (snap.exists()) {
      const data = snap.data() as any;
      setEmail(data.email || "");
      setAppPass(data.appPass || "");
    } else {
      setEmail("");
      setAppPass("");
    }
    setLoaded(true);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    // field-level validation with tooltip
    if (!email || !String(email).trim()) {
      setFieldError({
        field: "email",
        msg: "このフィールドを入力してください。",
      });
      setLoading(false);
      return;
    }
    const emailRe = /^\S+@\S+\.\S+$/;
    if (!emailRe.test(email)) {
      setFieldError({
        field: "email",
        msg: "有効なメールアドレスを入力してください。",
      });
      setLoading(false);
      return;
    }
    if (!appPass || appPass.length !== 16) {
      setFieldError({
        field: "appPass",
        msg: "英数字16文字で入力してください。",
      });
      setLoading(false);
      return;
    }
    const user = await waitForAuthReady();
    if (!user) {
      alert("未ログインです。ログインしてください。");
      setLoading(false);
      return;
    }
    const db = getFirestore();
    const uid = (user as any).uid;
    const collectionName =
      siteType === "jobbox" ? "mail_settings" : "engage_mail_settings";
    const docRef = doc(db, "accounts", uid, collectionName, "settings");
    await setDoc(docRef, { email, appPass, createdAt: Date.now() });
    await loadSetting();
    setSuccessMsg("✅ 保存しました！");
    setFieldError(null);
    setTimeout(() => setSuccessMsg(""), 3000);
    setLoading(false);
  }

  async function handleDelete() {
    const user = await waitForAuthReady();
    if (!user) return;
    const db = getFirestore();
    const uid = (user as any).uid;
    const collectionName =
      siteType === "jobbox" ? "mail_settings" : "engage_mail_settings";
    await deleteDoc(doc(db, "accounts", uid, collectionName, "settings"));
    setEmail("");
    setAppPass("");
    setLoaded(true);
  }

  return (
    <div style={{ padding: 28 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12 }}>
        メール設定
      </h2>
      <p style={{ marginBottom: 24 }}>
        RoMeALLで監視するメールアドレスとアプリパスワード(16桁)を登録 /
        管理することができます。
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
                メールアドレス
              </label>
              <div className="field-tooltip-wrapper">
                <input
                  name="mail_settings_email"
                  autoComplete="off"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    if (fieldError && fieldError.field === "email")
                      setFieldError(null);
                  }}
                  placeholder="sample@company.com"
                  className="input"
                  style={{ width: "100%", boxSizing: "border-box" }}
                />
                {fieldError && fieldError.field === "email" && (
                  <div className="field-tooltip-bubble" aria-hidden>
                    <div className="field-tooltip-box">
                      <div className="field-tooltip-icon">!</div>
                      <div>{fieldError.msg}</div>
                    </div>
                  </div>
                )}
              </div>
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
                アプリパスワード
              </label>
              <div className="input-with-icon">
                <div
                  className="field-tooltip-wrapper"
                  style={{ width: "100%" }}
                >
                  <input
                    name="mail_settings_apppass"
                    autoComplete="new-password"
                    type={showPass ? "text" : "password"}
                    value={appPass}
                    onChange={(e) => {
                      setAppPass(e.target.value);
                      if (fieldError && fieldError.field === "appPass")
                        setFieldError(null);
                    }}
                    placeholder="英数字16文字（スペースなし）"
                    className="input"
                    style={{ width: "100%", boxSizing: "border-box" }}
                  />
                  {fieldError && fieldError.field === "appPass" && (
                    <div className="field-tooltip-bubble" aria-hidden>
                      <div className="field-tooltip-box">
                        <div className="field-tooltip-icon">!</div>
                        <div>{fieldError.msg}</div>
                      </div>
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setShowPass((s) => !s)}
                  aria-label={showPass ? "隠す" : "表示"}
                  className="password-toggle"
                >
                  {showPass ? (
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
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          </div>

          <button className="btn" type="submit" disabled={loading}>
            {loading ? "保存中..." : "保存"}
          </button>

          {successMsg && (
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                color: "#28a745",
                marginTop: 8,
                fontWeight: 700,
              }}
            >
              {successMsg}
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
