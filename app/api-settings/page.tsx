"use client";

import React, { useEffect, useState } from "react";
import { getClientAuth } from "../../lib/firebaseClient";
import { getFirestore, doc, getDoc, setDoc } from "firebase/firestore";

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

export default function ApiSettingsPage() {
  const [baseUrl, setBaseUrl] = useState("");
  const [apiId, setApiId] = useState("");
  const [apiPass, setApiPass] = useState("");
  const [provider, setProvider] = useState("sms_publisher");
  const [showPass, setShowPass] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [fieldError, setFieldError] = useState<{
    field: string;
    msg: string;
  } | null>(null);

  useEffect(() => {
    loadSetting();
  }, []);

  async function loadSetting() {
    const user = await waitForAuthReady();
    if (!user) return;
    try {
      const db = getFirestore();
      const uid = (user as any).uid;
      const docRef = doc(db, "accounts", uid, "api_settings", "settings");
      const snap = await getDoc(docRef);
      if (snap.exists()) {
        const data = snap.data() as any;
        setProvider(data.provider || "sms_publisher");
        setBaseUrl(data.baseUrl || "");
        setApiId(data.apiId || "");
        setApiPass(data.apiPass || "");
      }
    } catch (e) {
      console.error("load api settings error", e);
    } finally {
      setLoaded(true);
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    // validate required fields (no blank entries) - show field-level tooltip
    if (!baseUrl || !baseUrl.trim()) {
      setFieldError({
        field: "baseUrl",
        msg: "このフィールドを入力してください。",
      });
      setLoading(false);
      return;
    }
    if (!apiId || !apiId.trim()) {
      setFieldError({
        field: "apiId",
        msg: "このフィールドを入力してください。",
      });
      setLoading(false);
      return;
    }
    if (!apiPass || !apiPass.trim()) {
      setFieldError({
        field: "apiPass",
        msg: "このフィールドを入力してください。",
      });
      setLoading(false);
      return;
    }
    try {
      const user = await waitForAuthReady();
      if (!user) throw new Error("未ログインです。ログインしてください。");
      const db = getFirestore();
      const uid = (user as any).uid;
      const docRef = doc(db, "accounts", uid, "api_settings", "settings");
      await setDoc(
        docRef,
        { provider, baseUrl, apiId, apiPass, updatedAt: Date.now() },
        { merge: true }
      );
      setSaved(true);
      setFieldError(null);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: any) {
      console.error("save api settings error", e);
      setError(e?.message || "保存に失敗しました。");
    } finally {
      setLoading(false);
    }
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
        <h2 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>API設定</h2>
        <div>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            style={{ padding: "6px 8px" }}
          >
            <option value="sms_publisher">SMS PUBLISHER</option>
          </select>
        </div>
      </div>
      <p style={{ marginBottom: 24 }}>
        外部APIのURLとトークンを設定 / 管理することができます。
      </p>

      {/* White card container to match rpa-settings/mail-settings */}
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
          {/* Hidden autofill trap inputs: helps prevent browser from filling real fields */}
          <input
            style={{
              position: "absolute",
              left: -9999,
              top: "auto",
              width: 1,
              height: 1,
              opacity: 0,
            }}
            tabIndex={-1}
            aria-hidden="true"
            autoComplete="username"
            name="fakeuser_user"
          />
          <input
            style={{
              position: "absolute",
              left: -9999,
              top: "auto",
              width: 1,
              height: 1,
              opacity: 0,
            }}
            tabIndex={-1}
            aria-hidden="true"
            autoComplete="new-password"
            name="fakeuser_pass"
          />

          <div style={{ marginBottom: 12 }}>
            <label
              style={{
                display: "block",
                marginBottom: 6,
                fontSize: 14,
                fontWeight: 500,
              }}
            >
              APIベースURL
            </label>
            <div className="field-tooltip-wrapper">
              <input
                name="api_base_url"
                autoComplete="off"
                value={baseUrl}
                onChange={(e) => {
                  setBaseUrl(e.target.value);
                  if (fieldError && fieldError.field === "baseUrl")
                    setFieldError(null);
                }}
                placeholder="https://api……"
                className="input"
                style={{ width: "100%", boxSizing: "border-box" }}
              />
              {fieldError && fieldError.field === "baseUrl" && (
                <div className="field-tooltip-bubble" aria-hidden>
                  <div className="field-tooltip-box">
                    <div className="field-tooltip-icon">!</div>
                    <div>{fieldError.msg}</div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div style={{ marginBottom: 12 }}>
            <label
              style={{
                display: "block",
                marginBottom: 6,
                fontSize: 14,
                fontWeight: 500,
              }}
            >
              API ID
            </label>
            <div className="field-tooltip-wrapper">
              <input
                name="api_id"
                autoComplete="username"
                value={apiId}
                onChange={(e) => {
                  setApiId(e.target.value);
                  if (fieldError && fieldError.field === "apiId")
                    setFieldError(null);
                }}
                placeholder="sm000……"
                className="input"
                style={{ width: "100%", boxSizing: "border-box" }}
              />
              {fieldError && fieldError.field === "apiId" && (
                <div className="field-tooltip-bubble" aria-hidden>
                  <div className="field-tooltip-box">
                    <div className="field-tooltip-icon">!</div>
                    <div>{fieldError.msg}</div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div style={{ marginBottom: 12 }}>
            <label
              style={{
                display: "block",
                marginBottom: 6,
                fontSize: 14,
                fontWeight: 500,
              }}
            >
              APIパスワード
            </label>
            <div className="input-with-icon">
              <div className="field-tooltip-wrapper" style={{ width: "100%" }}>
                <input
                  name="api_password"
                  autoComplete="new-password"
                  type={showPass ? "text" : "password"}
                  value={apiPass}
                  onChange={(e) => {
                    setApiPass(e.target.value);
                    if (fieldError && fieldError.field === "apiPass")
                      setFieldError(null);
                  }}
                  placeholder="samplepassword"
                  className="input"
                  style={{ width: "100%", boxSizing: "border-box" }}
                />
                {fieldError && fieldError.field === "apiPass" && (
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

          <button className="btn" type="submit" disabled={loading}>
            {loading ? "保存中..." : "保存"}
          </button>
          {error && (
            <div style={{ color: "#ff0000", marginTop: 8 }}>{error}</div>
          )}
          {saved && (
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                color: "#28a745",
                marginTop: 8,
                fontWeight: 700,
              }}
            >
              ✅ 保存しました！
            </div>
          )}
        </form>
      </div>
    </div>
  );
}
