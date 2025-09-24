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
  const [showPass, setShowPass] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);

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
    try {
      const user = await waitForAuthReady();
      if (!user) throw new Error("未ログインです。ログインしてください。");
      const db = getFirestore();
      const uid = (user as any).uid;
      const docRef = doc(db, "accounts", uid, "api_settings", "settings");
      await setDoc(
        docRef,
        { baseUrl, apiId, apiPass, updatedAt: Date.now() },
        { merge: true }
      );
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: any) {
      console.error("save api settings error", e);
      alert(e?.message || "保存に失敗しました。");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ padding: 28 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12 }}>
        API設定
      </h2>
      <p style={{ marginBottom: 16 }}>
        外部APIのベースURLとトークンを設定します。
      </p>

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
          <label>APIベースURL</label>
          <input
            name="api_base_url"
            autoComplete="off"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box", marginTop: 6 }}
          />
        </div>

        <div style={{ marginBottom: 12 }}>
          <label>API ID</label>
          <input
            name="api_id"
            autoComplete="username"
            value={apiId}
            onChange={(e) => setApiId(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box", marginTop: 6 }}
          />
        </div>

        <div style={{ marginBottom: 12 }}>
          <label>APIパスワード</label>
          <div style={{ position: "relative" }}>
            <input
              name="api_password"
              autoComplete="new-password"
              type={showPass ? "text" : "password"}
              value={apiPass}
              onChange={(e) => setApiPass(e.target.value)}
              style={{
                width: "100%",
                boxSizing: "border-box",
                marginTop: 6,
                paddingRight: 44,
              }}
            />
            <button
              type="button"
              onClick={() => setShowPass((s) => !s)}
              aria-label={showPass ? "隠す" : "表示"}
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
                width: 28,
                height: 28,
              }}
            >
              {showPass ? (
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  aria-hidden
                >
                  <path
                    d="M3 3L21 21"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M10.58 10.58A3 3 0 0113.42 13.42"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M9.88 5.41A11 11 0 0121 12c-2 3.5-5.5 6-9 6a9.98 9.98 0 01-6.39-2.22"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              ) : (
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  aria-hidden
                >
                  <path
                    d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <circle
                    cx="12"
                    cy="12"
                    r="3"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </button>
          </div>
        </div>

        <button className="btn" type="submit" disabled={loading}>
          {loading ? "保存中..." : "保存"}
        </button>
        {saved && (
          <div
            className="msg"
            style={{ color: "var(--accent)", marginTop: 12, fontWeight: 700 }}
          >
            保存しました
          </div>
        )}
      </form>
    </div>
  );
}
