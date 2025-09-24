"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import {
  signInWithEmailAndPassword,
  sendPasswordResetEmail,
} from "firebase/auth";
import { getClientAuth } from "../../lib/firebaseClient";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);
    try {
      const clientAuth = getClientAuth();
      if (!clientAuth) throw new Error("Client auth unavailable");
      await signInWithEmailAndPassword(clientAuth, email, password);
      setMessage("ログインに成功しました。");
      // redirect to dashboard after successful login
      router.push("/dashboard");
    } catch (err: any) {
      setError(err?.message || "ログインに失敗しました。");
    } finally {
      setLoading(false);
    }
  };

  const handleForgot = () => {
    setError("");
    setMessage("");
    if (!email) {
      setError("パスワード再設定にはメールアドレスを入力してください。");
      return;
    }
    setShowModal(true);
  };

  const confirmSendReset = async () => {
    setShowModal(false);
    setLoading(true);
    try {
      const clientAuth = getClientAuth();
      if (!clientAuth) throw new Error("Client auth unavailable");
      await sendPasswordResetEmail(clientAuth, email);
      setMessage(
        "パスワード再設定メールを送信しました。メールを確認してください。"
      );
    } catch (err: any) {
      setError(err?.message || "メール送信に失敗しました。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="center">
      <div className="card">
        <h1 className="title">RPA_SMS & JOBBOX /// LOGIN</h1>

        <form onSubmit={handleLogin}>
          <div className="field-row">
            <label className="label">メールアドレス</label>
            <input
              type="email"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>

          <div className="field-row">
            <label className="label">パスワード</label>
            <input
              type="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button type="submit" disabled={loading} className="btn">
            {loading ? "処理中..." : "ログイン"}
          </button>
        </form>

        <div style={{ textAlign: "center" }}>
          <button onClick={handleForgot} className="link">
            パスワードをお忘れですか？
          </button>
        </div>

        {error && <p className="msg error">{error}</p>}
        {message && <p className="msg ok">{message}</p>}
      </div>
      {showModal && (
        <div className="modal-backdrop">
          <div className="modal">
            <h3>確認</h3>
            <div>パスワード再設定のメールを送信してもよろしいですか？</div>
            <div className="actions">
              <button
                className="btn-small secondary"
                onClick={() => setShowModal(false)}
              >
                キャンセル
              </button>
              <button className="btn-small" onClick={confirmSendReset}>
                送信する
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
