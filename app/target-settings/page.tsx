"use client";

import React, { useEffect, useState, useRef } from "react";
import { getClientAuth } from "../../lib/firebaseClient";
import {
  getFirestore,
  doc,
  getDoc,
  setDoc,
  collection,
  addDoc,
  updateDoc,
  deleteDoc,
  serverTimestamp,
  query,
  getDocs,
  orderBy,
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

export default function TargetSettingsPage() {
  const [nameTypes, setNameTypes] = useState({
    kanji: true,
    katakana: true,
    hiragana: true,
    alpha: true,
  });
  const [genders, setGenders] = useState({ male: true, female: true });
  const [ageRanges, setAgeRanges] = useState({
    maleMin: 18,
    maleMax: 99,
    femaleMin: 18,
    femaleMax: 99,
  });
  const [smsTemplateA, setSmsTemplateA] = useState("");
  const [smsTemplateB, setSmsTemplateB] = useState("");
  const [smsUseA, setSmsUseA] = useState(true);
  const [smsUseB, setSmsUseB] = useState(true);
  const [autoReply, setAutoReply] = useState(false);
  const [mailUseTarget, setMailUseTarget] = useState(true);
  const [mailUseNonTarget, setMailUseNonTarget] = useState(false);
  const [mailTemplateA, setMailTemplateA] = useState("");
  const [mailTemplateB, setMailTemplateB] = useState("");
  const [mailSubjectA, setMailSubjectA] = useState("");
  const [mailSubjectB, setMailSubjectB] = useState("");
  const [saved, setSaved] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);

  // 保存和删除状态
  const [saveMessage, setSaveMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);
  const [deleteDialog, setDeleteDialog] = useState<{
    show: boolean;
    segment?: Segment;
    onConfirm?: () => void;
  } | null>(null);

  // Segments (多条件分组) state
  type Segment = {
    id?: string;
    title: string;
    enabled: boolean;
    priority: number;
    conditions: {
      nameTypes: typeof nameTypes;
      genders: typeof genders;
      ageRanges: typeof ageRanges;
    };
    actions: {
      sms: { enabled: boolean; text: string };
      mail: { enabled: boolean; subject: string; body: string };
    };
  };
  const [segments, setSegments] = useState<Segment[]>([]);
  const [segFormOpen, setSegFormOpen] = useState(true);
  const [currentUser, setCurrentUser] = useState<any>(null);
  const [segDraft, setSegDraft] = useState<Segment>({
    title: "",
    enabled: true,
    priority: 0,
    conditions: {
      nameTypes: { kanji: true, katakana: true, hiragana: true, alpha: true },
      genders: { male: true, female: true },
      ageRanges: { maleMin: 18, maleMax: 99, femaleMin: 18, femaleMax: 99 },
    },
    actions: {
      sms: { enabled: true, text: "" },
      mail: { enabled: false, subject: "", body: "" },
    },
  });

  // 富文本编辑器组件
  const RichTextEditor = ({ value, onChange, placeholder }) => {
    const editorRef = useRef(null);
    const isComposingRef = useRef(false);

    const execCommand = (command, value = null) => {
      if (command === "italic") {
        // 对于斜体，使用CSS样式而不是document.execCommand，以支持中文
        const selection = window.getSelection();
        if (selection.rangeCount > 0) {
          const range = selection.getRangeAt(0);
          if (!range.collapsed) {
            const span = document.createElement("span");
            span.style.fontStyle = "italic";
            span.style.transform = "skew(-10deg)";
            span.style.display = "inline-block";
            try {
              range.surroundContents(span);
            } catch (e) {
              // 如果选择内容包含部分元素，使用extractContents
              span.appendChild(range.extractContents());
              range.insertNode(span);
            }
            selection.removeAllRanges();
          }
        }
      } else {
        document.execCommand(command, false, value);
      }
      if (editorRef.current) {
        onChange(editorRef.current.innerHTML);
      }
    };

    const handleInput = () => {
      if (editorRef.current && !isComposingRef.current) {
        onChange(editorRef.current.innerHTML);
      }
    };

    const handleCompositionStart = () => {
      isComposingRef.current = true;
    };

    const handleCompositionEnd = () => {
      isComposingRef.current = false;
      if (editorRef.current) {
        onChange(editorRef.current.innerHTML);
      }
    };

    // 只在初始化时设置内容，避免打字时重置
    useEffect(() => {
      if (editorRef.current && editorRef.current.innerHTML === "" && value) {
        editorRef.current.innerHTML = value;
      }
    }, []);

    return (
      <div style={{ border: "1px solid #ddd", borderRadius: 4 }}>
        {/* 工具栏 */}
        <div
          style={{
            padding: "8px 12px",
            borderBottom: "1px solid #eee",
            display: "flex",
            gap: 4,
            background: "#f8f9fa",
          }}
        >
          <button
            type="button"
            onClick={() => execCommand("bold")}
            style={{
              border: "none",
              background: "transparent",
              padding: "4px 8px",
              cursor: "pointer",
              borderRadius: 2,
              fontSize: 14,
              fontWeight: "bold",
            }}
            title="太字"
          >
            B
          </button>
          <button
            type="button"
            onClick={() => execCommand("italic")}
            style={{
              border: "none",
              background: "transparent",
              padding: "4px 8px",
              cursor: "pointer",
              borderRadius: 2,
              fontSize: 14,
              fontStyle: "italic",
            }}
            title="斜体"
          >
            I
          </button>
          <button
            type="button"
            onClick={() => execCommand("underline")}
            style={{
              border: "none",
              background: "transparent",
              padding: "4px 8px",
              cursor: "pointer",
              borderRadius: 2,
              fontSize: 14,
              textDecoration: "underline",
            }}
            title="下線"
          >
            U
          </button>
          <button
            type="button"
            onClick={() => {
              const url = prompt("リンクURLを入力してください:");
              if (url) execCommand("createLink", url);
            }}
            style={{
              border: "none",
              background: "transparent",
              padding: "4px 8px",
              cursor: "pointer",
              borderRadius: 2,
              fontSize: 14,
            }}
            title="リンク"
          >
            🔗
          </button>
          <button
            type="button"
            onClick={() => {
              const input = document.createElement("input");
              input.type = "file";
              input.accept = "image/*";
              input.onchange = (e) => {
                const target = e.target as HTMLInputElement;
                const file = target.files?.[0];
                if (file) {
                  // ここでファイルアップロード処理を実装可能
                  alert("ファイル添付機能は実装予定です");
                }
              };
              input.click();
            }}
            style={{
              border: "none",
              background: "transparent",
              padding: "4px 8px",
              cursor: "pointer",
              borderRadius: 2,
              fontSize: 14,
            }}
            title="添付"
          >
            📎
          </button>
        </div>

        {/* 編集エリア */}
        <div
          ref={editorRef}
          contentEditable
          onInput={handleInput}
          onCompositionStart={handleCompositionStart}
          onCompositionEnd={handleCompositionEnd}
          style={{
            minHeight: 120,
            padding: "12px",
            fontSize: 14,
            lineHeight: "1.5",
            outline: "none",
            background: "#fff",
          }}
          data-placeholder={placeholder}
          suppressContentEditableWarning={true}
        />

        <style jsx>{`
          div[contenteditable]:empty:before {
            content: attr(data-placeholder);
            color: #999;
            font-style: italic;
          }
          div[contenteditable] span[style*="italic"] {
            font-style: italic;
            transform: skew(-10deg);
            display: inline-block;
          }
          div[contenteditable] em,
          div[contenteditable] i {
            font-style: italic;
            transform: skew(-10deg);
            display: inline-block;
          }
        `}</style>
      </div>
    );
  };

  useEffect(() => {
    async function initAuth() {
      const user = await waitForAuthReady();
      console.log("Current user:", user);
      setCurrentUser(user);
      if (user) {
        loadSetting();
        loadSegments();
      }
    }
    initAuth();
  }, []);

  async function loadSetting() {
    const user = await waitForAuthReady();
    if (!user) return;
    try {
      const db = getFirestore();
      const uid = (user as any).uid;
      const docRef = doc(db, "accounts", uid, "target_settings", "settings");
      const snap = await getDoc(docRef);
      if (snap.exists()) {
        const data = snap.data() as any;
        // backward-compat: if old `kana` flag exists, apply to both katakana and hiragana
        const oldKana = data.nameTypes?.kana;
        setNameTypes({
          kanji: data.nameTypes?.kanji ?? true,
          katakana:
            oldKana !== undefined ? oldKana : data.nameTypes?.katakana ?? true,
          hiragana:
            oldKana !== undefined ? oldKana : data.nameTypes?.hiragana ?? true,
          alpha: data.nameTypes?.alpha ?? true,
        });
        setGenders({
          male: data.genders?.male ?? true,
          female: data.genders?.female ?? true,
        });
        setAgeRanges({
          maleMin: data.ageRanges?.maleMin ?? 18,
          maleMax: data.ageRanges?.maleMax ?? 99,
          femaleMin: data.ageRanges?.femaleMin ?? 18,
          femaleMax: data.ageRanges?.femaleMax ?? 99,
        });
        setSmsTemplateA(data.smsTemplateA ?? "");
        setSmsTemplateB(data.smsTemplateB ?? "");
        setSmsUseA(data.smsUseA === undefined ? true : !!data.smsUseA);
        setSmsUseB(data.smsUseB === undefined ? true : !!data.smsUseB);
        setAutoReply(data.autoReply === undefined ? false : !!data.autoReply);
        setMailUseTarget(
          data.mailUseTarget === undefined ? true : !!data.mailUseTarget
        );
        setMailUseNonTarget(
          data.mailUseNonTarget === undefined ? false : !!data.mailUseNonTarget
        );
        setMailTemplateA(data.mailTemplateA ?? "");
        setMailTemplateB(data.mailTemplateB ?? "");
        setMailSubjectA(data.mailSubjectA ?? "");
        setMailSubjectB(data.mailSubjectB ?? "");
      }
    } catch (e) {
      console.error("load target settings error", e);
    } finally {
      setLoaded(true);
    }
  }

  async function loadSegments() {
    try {
      const user = await waitForAuthReady();
      console.log("loadSegments user:", user);
      if (!user) {
        console.log("No user found, skipping loadSegments");
        return;
      }
      const db = getFirestore();
      const uid = (user as any).uid;
      console.log("loadSegments uid:", uid);
      const coll = collection(db, "accounts", uid, "target_segments");
      const q = query(coll, orderBy("priority", "asc"));
      const snap = await getDocs(q);
      const list: Segment[] = [];
      snap.forEach((d) => {
        const v = d.data() as any;
        list.push({ id: d.id, ...(v as any) });
      });
      console.log("Loaded segments:", list);
      setSegments(list);
    } catch (e: any) {
      console.error("loadSegments error", e);
      if (e?.code === "permission-denied") {
        console.log("Permission denied for loadSegments");
      }
      setSegments([]);
    }
  }

  async function saveSegment() {
    try {
      const user = await waitForAuthReady();
      console.log("saveSegment user:", user);
      if (!user) {
        setSaveMessage({
          type: "error",
          text: "ログインが必要です。ログインページに移動してください。",
        });
        setTimeout(() => (window.location.href = "/login"), 2000);
        return;
      }

      // 详细检查用户信息
      console.log("User details:", {
        uid: user.uid,
        email: user.email,
        emailVerified: user.emailVerified,
        accessToken: await user.getIdToken(),
      });

      const db = getFirestore();
      const uid = (user as any).uid;
      console.log("saveSegment uid:", uid);

      if (!segDraft.title.trim()) {
        setSaveMessage({
          type: "error",
          text: "条件タイトルを入力してください。",
        });
        return;
      }

      console.log("Saving segment:", segDraft);

      // 测试基本的写权限
      console.log(
        "Testing write permission to path: accounts/" + uid + "/target_segments"
      );

      // Update if editing existing segment (has id), else add new
      if (segDraft.id) {
        console.log("Updating existing segment:", segDraft.id);
        await updateDoc(
          doc(db, "accounts", uid, "target_segments", segDraft.id),
          {
            title: segDraft.title.trim(),
            enabled: !!segDraft.enabled,
            priority: Number(segDraft.priority) || 0,
            conditions: segDraft.conditions,
            actions: segDraft.actions,
            updatedAt: serverTimestamp(),
          }
        );
      } else {
        console.log("Creating new segment");
        const coll = collection(db, "accounts", uid, "target_segments");
        await addDoc(coll, {
          title: segDraft.title.trim(),
          enabled: !!segDraft.enabled,
          priority: Number(segDraft.priority) || 0,
          conditions: segDraft.conditions,
          actions: segDraft.actions,
          createdAt: serverTimestamp(),
          updatedAt: serverTimestamp(),
        });
      }

      console.log("Segment saved successfully");

      setSegDraft({
        id: undefined as any,
        title: "",
        enabled: true,
        priority: 0,
        conditions: {
          nameTypes: {
            kanji: true,
            katakana: true,
            hiragana: true,
            alpha: true,
          },
          genders: { male: true, female: true },
          ageRanges: { maleMin: 18, maleMax: 99, femaleMin: 18, femaleMax: 99 },
        },
        actions: {
          sms: { enabled: true, text: "" },
          mail: { enabled: false, subject: "", body: "" },
        },
      });
      setSegFormOpen(false);
      loadSegments();
      setSaveMessage({ type: "success", text: "保存しました！" });
      setTimeout(() => setSaveMessage(null), 3000);
    } catch (e: any) {
      console.error("saveSegment error", e);
      if (e?.code === "permission-denied") {
        setSaveMessage({
          type: "error",
          text: "権限がありません。ログインし直してください。",
        });
        setTimeout(() => (window.location.href = "/login"), 2000);
      } else {
        setSaveMessage({
          type: "error",
          text: e?.message || "保存に失敗しました。",
        });
      }
    }
  }

  async function deleteSegment(id?: string) {
    if (!id) return;
    try {
      const user = await waitForAuthReady();
      if (!user) throw new Error("未ログインです。ログインしてください。");
      const db = getFirestore();
      const uid = (user as any).uid;
      await deleteDoc(doc(db, "accounts", uid, "target_segments", id));
      loadSegments();
      setDeleteDialog(null);
    } catch (e) {
      console.error("deleteSegment error", e);
    }
  }

  function showDeleteDialog(segment: Segment) {
    setDeleteDialog({
      show: true,
      segment,
      onConfirm: () => deleteSegment(segment.id),
    });
  }

  function editSegment(seg: Segment) {
    setSegDraft({ ...seg });
    setSegFormOpen(true);
  }

  async function toggleSegment(id?: string, enabled?: boolean) {
    if (!id) return;
    try {
      const user = await waitForAuthReady();
      if (!user) throw new Error("未ログインです。ログインしてください。");
      const db = getFirestore();
      const uid = (user as any).uid;
      await updateDoc(doc(db, "accounts", uid, "target_segments", id), {
        enabled: !enabled,
        updatedAt: Date.now(),
      });
      loadSegments();
    } catch (e) {
      console.error("toggleSegment error", e);
    }
  }

  return (
    <div style={{ padding: 28 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12 }}>
        対象設定
      </h2>
      <p style={{ marginBottom: 16 }}>
        RPAが対象とする求職者を絞り込む設定です。
      </p>

      {/* Debug info */}

      {/* Segments (multi-conditions) manager - 完全按照截图重新设计 */}
      <div style={{ marginTop: 24 }}>
        <div
          style={{
            background: "rgba(255,255,255,0.98)",
            border: "1px solid rgba(0,0,0,0.08)",
            borderRadius: 8,
            padding: 20,
          }}
        >
          {/* 保存タイトル */}
          <div style={{ marginBottom: 16 }}>
            <label
              style={{
                display: "block",
                marginBottom: 8,
                fontSize: 14,
                color: "#333",
              }}
            >
              保存タイトル
            </label>
            <input
              type="text"
              value={segDraft.title}
              onChange={(e) =>
                setSegDraft((s) => ({ ...s, title: e.target.value }))
              }
              placeholder="保存タイトル"
              style={{
                width: "100%",
                maxWidth: 320,
                padding: "8px 12px",
                border: "1px solid #ddd",
                borderRadius: 4,
                fontSize: 14,
                boxSizing: "border-box",
              }}
            />
          </div>

          {/* 送信先 */}
          <div style={{ marginBottom: 20 }}>
            <label
              style={{
                display: "block",
                marginBottom: 8,
                fontSize: 14,
                color: "#333",
              }}
            >
              送信先
            </label>
            <div style={{ display: "flex", gap: 16 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={segDraft.actions.sms.enabled}
                  onChange={(e) =>
                    setSegDraft((s) => ({
                      ...s,
                      actions: {
                        ...s.actions,
                        sms: { ...s.actions.sms, enabled: e.target.checked },
                      },
                    }))
                  }
                />
                SMS
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={segDraft.actions.mail.enabled}
                  onChange={(e) =>
                    setSegDraft((s) => ({
                      ...s,
                      actions: {
                        ...s.actions,
                        mail: { ...s.actions.mail, enabled: e.target.checked },
                      },
                    }))
                  }
                />
                メール
              </label>
            </div>
          </div>

          {/* 氏名 */}
          <div style={{ marginBottom: 20 }}>
            <label
              style={{
                display: "block",
                marginBottom: 8,
                fontSize: 14,
                color: "#333",
              }}
            >
              氏名
            </label>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={segDraft.conditions.nameTypes.kanji}
                  onChange={(e) =>
                    setSegDraft((s) => ({
                      ...s,
                      conditions: {
                        ...s.conditions,
                        nameTypes: {
                          ...s.conditions.nameTypes,
                          kanji: e.target.checked,
                        },
                      },
                    }))
                  }
                />
                漢字名
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={segDraft.conditions.nameTypes.katakana}
                  onChange={(e) =>
                    setSegDraft((s) => ({
                      ...s,
                      conditions: {
                        ...s.conditions,
                        nameTypes: {
                          ...s.conditions.nameTypes,
                          katakana: e.target.checked,
                        },
                      },
                    }))
                  }
                />
                カタカナ名
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={segDraft.conditions.nameTypes.hiragana}
                  onChange={(e) =>
                    setSegDraft((s) => ({
                      ...s,
                      conditions: {
                        ...s.conditions,
                        nameTypes: {
                          ...s.conditions.nameTypes,
                          hiragana: e.target.checked,
                        },
                      },
                    }))
                  }
                />
                ひらがな名
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={segDraft.conditions.nameTypes.alpha}
                  onChange={(e) =>
                    setSegDraft((s) => ({
                      ...s,
                      conditions: {
                        ...s.conditions,
                        nameTypes: {
                          ...s.conditions.nameTypes,
                          alpha: e.target.checked,
                        },
                      },
                    }))
                  }
                />
                アルファベット名
              </label>
            </div>
          </div>

          {/* 年齢範囲 */}
          <div style={{ marginBottom: 20 }}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 24,
              }}
            >
              <div>
                <label
                  style={{
                    display: "block",
                    marginBottom: 8,
                    fontSize: 14,
                    color: "#333",
                  }}
                >
                  男性の年齢範囲
                </label>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="number"
                    value={segDraft.conditions.ageRanges.maleMin}
                    onChange={(e) =>
                      setSegDraft((s) => ({
                        ...s,
                        conditions: {
                          ...s.conditions,
                          ageRanges: {
                            ...s.conditions.ageRanges,
                            maleMin: Number(e.target.value),
                          },
                        },
                      }))
                    }
                    style={{
                      width: 70,
                      padding: "6px 8px",
                      border: "1px solid #ddd",
                      borderRadius: 4,
                      textAlign: "center",
                    }}
                  />
                  <span>歳</span>
                  <span>-</span>
                  <input
                    type="number"
                    value={segDraft.conditions.ageRanges.maleMax}
                    onChange={(e) =>
                      setSegDraft((s) => ({
                        ...s,
                        conditions: {
                          ...s.conditions,
                          ageRanges: {
                            ...s.conditions.ageRanges,
                            maleMax: Number(e.target.value),
                          },
                        },
                      }))
                    }
                    style={{
                      width: 70,
                      padding: "6px 8px",
                      border: "1px solid #ddd",
                      borderRadius: 4,
                      textAlign: "center",
                    }}
                  />
                  <span>歳</span>
                </div>
              </div>
              <div>
                <label
                  style={{
                    display: "block",
                    marginBottom: 8,
                    fontSize: 14,
                    color: "#333",
                  }}
                >
                  女性の年齢範囲
                </label>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input
                    type="number"
                    value={segDraft.conditions.ageRanges.femaleMin}
                    onChange={(e) =>
                      setSegDraft((s) => ({
                        ...s,
                        conditions: {
                          ...s.conditions,
                          ageRanges: {
                            ...s.conditions.ageRanges,
                            femaleMin: Number(e.target.value),
                          },
                        },
                      }))
                    }
                    style={{
                      width: 70,
                      padding: "6px 8px",
                      border: "1px solid #ddd",
                      borderRadius: 4,
                      textAlign: "center",
                    }}
                  />
                  <span>歳</span>
                  <span>-</span>
                  <input
                    type="number"
                    value={segDraft.conditions.ageRanges.femaleMax}
                    onChange={(e) =>
                      setSegDraft((s) => ({
                        ...s,
                        conditions: {
                          ...s.conditions,
                          ageRanges: {
                            ...s.conditions.ageRanges,
                            femaleMax: Number(e.target.value),
                          },
                        },
                      }))
                    }
                    style={{
                      width: 70,
                      padding: "6px 8px",
                      border: "1px solid #ddd",
                      borderRadius: 4,
                      textAlign: "center",
                    }}
                  />
                  <span>歳</span>
                </div>
              </div>
            </div>
          </div>

          {/* SMS内容 */}
          {segDraft.actions.sms.enabled && (
            <div style={{ marginBottom: 20 }}>
              <textarea
                value={segDraft.actions.sms.text}
                onChange={(e) =>
                  setSegDraft((s) => ({
                    ...s,
                    actions: {
                      ...s.actions,
                      sms: { ...s.actions.sms, text: e.target.value },
                    },
                  }))
                }
                placeholder="【xxx株式会社】ご応募いただいた求人について……https://line..."
                rows={5}
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  border: "1px solid #ccc",
                  borderRadius: 4,
                  fontSize: 14,
                  boxSizing: "border-box",
                  resize: "vertical",
                  fontFamily: "inherit",
                  lineHeight: "1.4",
                }}
              />
            </div>
          )}

          {/* メール内容 */}
          {segDraft.actions.mail.enabled && (
            <div style={{ marginBottom: 20 }}>
              <input
                type="text"
                value={segDraft.actions.mail.subject}
                onChange={(e) =>
                  setSegDraft((s) => ({
                    ...s,
                    actions: {
                      ...s.actions,
                      mail: { ...s.actions.mail, subject: e.target.value },
                    },
                  }))
                }
                placeholder="件名"
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  border: "1px solid #ddd",
                  borderRadius: 4,
                  fontSize: 14,
                  boxSizing: "border-box",
                  marginBottom: 8,
                }}
              />

              <RichTextEditor
                value={segDraft.actions.mail.body}
                onChange={(htmlContent) =>
                  setSegDraft((s) => ({
                    ...s,
                    actions: {
                      ...s.actions,
                      mail: { ...s.actions.mail, body: htmlContent },
                    },
                  }))
                }
                placeholder="お忙しい中ご応募ありがとうございます。xxx株式会社です。下記よりLINE登録をお願いいたします！https://line..."
              />
            </div>
          )}

          {/* 保存ボタン */}
          <div style={{ textAlign: "center", marginTop: 24 }}>
            <button
              onClick={saveSegment}
              style={{
                background: "#333",
                color: "#fff",
                border: "none",
                borderRadius: 4,
                padding: "12px 40px",
                fontSize: 14,
                fontWeight: 500,
                cursor: "pointer",
                minWidth: 120,
              }}
            >
              保存
            </button>

            {/* 保存メッセージ */}
            {saveMessage && (
              <div
                style={{
                  marginTop: 12,
                  padding: "8px 16px",
                  borderRadius: 4,
                  fontSize: 14,
                  fontWeight: 500,
                  background:
                    saveMessage.type === "success" ? "#d4edda" : "#f8d7da",
                  color: saveMessage.type === "success" ? "#155724" : "#721c24",
                  border: `1px solid ${
                    saveMessage.type === "success" ? "#c3e6cb" : "#f5c6cb"
                  }`,
                  display: "block",
                  maxWidth: "400px",
                  margin: "12px auto 0",
                }}
              >
                {saveMessage.type === "success" ? "✅" : "❌"}{" "}
                {saveMessage.text}
              </div>
            )}
          </div>
        </div>

        {/* 保存済み対象条件リスト */}
        <div style={{ marginTop: 24 }}>
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>
              保存済み対象条件
            </h3>
          </div>

          <div style={{ display: "grid", gap: 12 }}>
            {segments.length === 0 && (
              <div
                style={{
                  color: "#666",
                  padding: "20px",
                  textAlign: "center",
                  background: "#f9f9f9",
                  borderRadius: 4,
                }}
              >
                まだ条件がありません。
              </div>
            )}

            {segments.map((s) => (
              <div
                key={s.id}
                style={{
                  background: s.enabled ? "#fff" : "#f8f9fa",
                  border: `1px solid ${
                    s.enabled ? "rgba(0,0,0,0.08)" : "#ddd"
                  }`,
                  borderRadius: 8,
                  padding: 16,
                  opacity: s.enabled ? 1 : 0.7,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginBottom: 12,
                  }}
                >
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 12 }}
                  >
                    <label
                      style={{
                        display: "flex",
                        alignItems: "center",
                        cursor: "pointer",
                        fontSize: 14,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={s.enabled}
                        onChange={() => toggleSegment(s.id, s.enabled)}
                        style={{ marginRight: 8 }}
                      />
                      <div
                        style={{
                          fontWeight: 600,
                          fontSize: 16,
                          color: s.enabled ? "#333" : "#666",
                        }}
                      >
                        {s.title || "(無題)"}
                      </div>
                    </label>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      onClick={() => editSegment(s)}
                      style={{
                        background: "#f8f9fa",
                        border: "1px solid #ddd",
                        padding: "6px 12px",
                        borderRadius: 4,
                        fontSize: 12,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                      }}
                      title="編集"
                    >
                      ✏️ 編集
                    </button>
                    <button
                      onClick={() => showDeleteDialog(s)}
                      style={{
                        background: "#fff",
                        border: "1px solid #dc3545",
                        color: "#dc3545",
                        padding: "6px 12px",
                        borderRadius: 4,
                        fontSize: 12,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                      }}
                      title="削除"
                    >
                      🗑️ 削除
                    </button>
                  </div>
                </div>

                {/* 条件の詳細表示 */}
                <div style={{ fontSize: 13, color: "#666", marginBottom: 8 }}>
                  <div style={{ marginBottom: 4 }}>
                    <strong>対象:</strong>
                    {Object.entries(s.conditions.nameTypes)
                      .filter(([key, enabled]) => enabled)
                      .map(([key]) => {
                        const labels = {
                          kanji: "漢字名",
                          katakana: "カタカナ名",
                          hiragana: "ひらがな名",
                          alpha: "アルファベット名",
                        } as any;
                        return labels[key];
                      })
                      .join("・") || "なし"}
                  </div>
                  <div style={{ marginBottom: 4 }}>
                    <strong>性別・年齢:</strong>
                    {s.conditions.genders.male &&
                      `男性 ${s.conditions.ageRanges.maleMin}-${s.conditions.ageRanges.maleMax}歳`}
                    {s.conditions.genders.male &&
                      s.conditions.genders.female &&
                      " / "}
                    {s.conditions.genders.female &&
                      `女性 ${s.conditions.ageRanges.femaleMin}-${s.conditions.ageRanges.femaleMax}歳`}
                  </div>
                </div>

                {/* アクションの詳細表示 */}
                <div style={{ fontSize: 12, color: "#666" }}>
                  <div style={{ display: "flex", gap: 16 }}>
                    {s.actions.sms.enabled && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        📱 <span>SMS送信</span>
                      </div>
                    )}
                    {s.actions.mail.enabled && (
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        📧{" "}
                        <span>
                          メール送信: {s.actions.mail.subject || "件名未設定"}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 削除確認ダイアログ */}
      {deleteDialog?.show && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
        >
          <div
            style={{
              background: "#fff",
              borderRadius: 8,
              padding: 24,
              maxWidth: 400,
              width: "90%",
              boxShadow: "0 4px 20px rgba(0, 0, 0, 0.15)",
            }}
          >
            <h3 style={{ margin: "0 0 16px 0", fontSize: 18, fontWeight: 600 }}>
              削除の確認
            </h3>
            <p style={{ margin: "0 0 20px 0", fontSize: 14, lineHeight: 1.5 }}>
              「{deleteDialog.segment?.title}」を削除しますか？
              <br />
              この操作は元に戻せません。
            </p>
            <div
              style={{ display: "flex", gap: 12, justifyContent: "flex-end" }}
            >
              <button
                onClick={() => setDeleteDialog(null)}
                style={{
                  background: "#f8f9fa",
                  border: "1px solid #ddd",
                  color: "#333",
                  padding: "8px 16px",
                  borderRadius: 4,
                  fontSize: 14,
                  cursor: "pointer",
                }}
              >
                キャンセル
              </button>
              <button
                onClick={deleteDialog.onConfirm}
                style={{
                  background: "#dc3545",
                  border: "none",
                  color: "#fff",
                  padding: "8px 16px",
                  borderRadius: 4,
                  fontSize: 14,
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
