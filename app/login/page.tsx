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
  const [showPassword, setShowPassword] = useState(false);

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
      // Firebase authentication error handling
      if (
        err?.code === "auth/wrong-password" ||
        err?.code === "auth/user-not-found" ||
        err?.code === "auth/invalid-credential"
      ) {
        setError("メールアドレスまたはパスワードが誤っています。");
      } else if (err?.code === "auth/too-many-requests") {
        setError(
          "試行回数が多すぎます。しばらくしてからもう一度お試しください。"
        );
      } else {
        setError("ログインに失敗しました。");
      }
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
        {/* 只保留美化后的品牌区块：使用静态图片（请将你的 logo 文件放到 public/logo.png） */}
        <div className="brand-block">
          {/* 使用原生 img，避免 next/image 的构建/配置差异；把你的附件保存为 public/logo.png 即可生效 */}
          <img src="/logo.png" alt="RoMeALL Logo" className="logo-image" />
          <h1 className="title">
            RoMe<span className="title-accent">ALL</span>
          </h1>
          <p className="subtitle">The robot works for me on all tasks.</p>
        </div>

        <form onSubmit={handleLogin}>
          <div className="field-row">
            <label className="label">メールアドレス</label>
            <input
              type="email"
              className="input"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="example@company.com"
              required
            />
          </div>

          <div className="field-row">
            <label className="label">パスワード</label>
            <div className="input-with-icon">
              <input
                type={showPassword ? "text" : "password"}
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="パスワードを入力してください"
                required
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword(!showPassword)}
              >
                {showPassword ? (
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
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
