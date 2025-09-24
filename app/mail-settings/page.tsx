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

export default function MailSettingsPage() {
  const [email, setEmail] = useState("");
  const [appPass, setAppPass] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [showPass, setShowPass] = useState(false);
  const [successMsg, setSuccessMsg] = useState("");

  useEffect(() => {
    loadSetting();
  }, []);

  async function loadSetting() {
    const user = await waitForAuthReady();
    if (!user) return;
    const db = getFirestore();
    const uid = (user as any).uid;
    const docRef = doc(db, "accounts", uid, "mail_settings", "settings");
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
    if (!email || appPass.length !== 16) {
      alert("メールと16桁の専用パスワードを正しく入力してください（16桁）");
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
    const docRef = doc(db, "accounts", uid, "mail_settings", "settings");
    await setDoc(docRef, { email, appPass, createdAt: Date.now() });
    await loadSetting();
    setSuccessMsg("保存しました");
    setTimeout(() => setSuccessMsg(""), 3000);
    setLoading(false);
  }

  async function handleDelete() {
    const user = await waitForAuthReady();
    if (!user) return;
    const db = getFirestore();
    const uid = (user as any).uid;
    await deleteDoc(doc(db, "accounts", uid, "mail_settings", "settings"));
    setEmail("");
    setAppPass("");
    setLoaded(true);
  }

  return (
    <div style={{ padding: 28 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12 }}>
        メール設定
      </h2>
      <p style={{ marginBottom: 16 }}>
        メール監視用アカウントと16桁の専用パスワードを保存します。RPA実行時にクラウドから読み込みます。
      </p>

      <form onSubmit={handleSave} autoComplete="off">
        {/* Hidden fields to trap browser autofill (do not remove) */}
        <div
          style={{ position: "absolute", left: -9999, top: -9999, opacity: 0 }}
          aria-hidden
        >
          <input name="fake-username" type="text" autoComplete="username" />
          <input
            name="fake-password"
            type="password"
            autoComplete="current-password"
          />
        </div>
        <table
          style={{ width: "100%", marginBottom: 12, tableLayout: "fixed" }}
        >
          <colgroup>
            <col style={{ width: "40%" }} />
            <col style={{ width: "60%" }} />
          </colgroup>
          <tbody>
            <tr>
              <td style={{ verticalAlign: "top" }}>
                <label>監視メールアドレス</label>
                <input
                  name="mail_settings_email"
                  autoComplete="off"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  style={{ width: "100%", boxSizing: "border-box" }}
                />
              </td>
              <td>
                <label>16桁の専用パスワード</label>
                <div style={{ position: "relative" }}>
                  <input
                    name="mail_settings_apppass"
                    autoComplete="new-password"
                    type={showPass ? "text" : "password"}
                    value={appPass}
                    onChange={(e) => setAppPass(e.target.value)}
                    required
                    style={{
                      width: "100%",
                      paddingRight: 44,
                      boxSizing: "border-box",
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
                      zIndex: 3,
                    }}
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
                        <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-5 0-9.27-3-11-7 1.11-2.45 2.98-4.44 5.23-5.66" />
                        <path d="M1 1l22 22" />
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
              </td>
            </tr>
          </tbody>
        </table>

        <button className="btn" type="submit" disabled={loading}>
          {loading ? "保存中..." : "保存"}
        </button>
      </form>

      {successMsg && (
        <div
          className="msg"
          style={{ color: "var(--accent)", marginTop: 12, fontWeight: 700 }}
        >
          {successMsg}
        </div>
      )}
    </div>
  );
}
