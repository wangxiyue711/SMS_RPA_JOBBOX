"use client";

import React, { useEffect, useState, useRef } from "react";
import { getClientAuth } from "../../lib/firebaseClient";

type SiteType = "jobbox" | "engage";
import {
  getFirestore,
  doc,
  collection,
  query,
  orderBy,
  getDocs,
  addDoc,
  updateDoc,
  serverTimestamp,
  deleteDoc,
  getDoc,
  writeBatch,
} from "firebase/firestore";

const serializePlaceholdersFromHtml = (html: string) => {
  if (!html) return "";
  if (typeof document === "undefined") return html;
  const div = document.createElement("div");
  div.innerHTML = html;
  const spans = div.querySelectorAll("span[data-placeholder]");
  spans.forEach((s) => {
    const key = s.getAttribute("data-placeholder") || "";
    const token = `{{${key}}}`;
    const tn = document.createTextNode(token);
    s.parentNode?.replaceChild(tn, s);
  });
  return div.innerHTML;
};

const tokensToHtml = (text: string) => {
  if (!text) return "";
  const map: Record<string, string> = {
    applicant_name: "{{氏名}}",
    name: "{{氏名}}",
    job_title: "{{職種}}",
    position: "{{職種}}",
    employer_name: "{{会社名}}",
    employer: "{{会社名}}",
  };
  return text.replace(/{{\s*([a-zA-Z0-9_]+)\s*}}/g, (m, key) => {
    const label = map[key] || `{{${key}}}`;
    return `<span data-placeholder="${key}" contenteditable="false" style="background:#fff3cd;border:1px solid #ffeeba;padding:2px 6px;border-radius:4px;margin:0 2px;display:inline-block;user-select:none">${label}</span>`;
  });
};
// RichTextEditor: 简洁、稳定的实现，支持通过 body 工具栏在 subject 或 body 中插入占位符
type RichTextEditorProps = {
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
  // Callback used to request insertion into subject. Should return true if handled.
  onInsertIntoSubject?: (token: string) => boolean;
  subjectRef?: React.RefObject<HTMLInputElement>;
};

const RichTextEditor: React.FC<RichTextEditorProps> = ({
  value,
  onChange,
  placeholder,
  onInsertIntoSubject,
  subjectRef,
}) => {
  const editorRef = useRef<HTMLDivElement | null>(null);
  const isComposingRef = useRef(false);
  const [showLinkDialog, setShowLinkDialog] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const savedRangeRef = useRef<Range | null>(null);

  const saveSelection = () => {
    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0)
      savedRangeRef.current = sel.getRangeAt(0).cloneRange();
  };

  const restoreSelection = () => {
    if (savedRangeRef.current) {
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(savedRangeRef.current);
      editorRef.current?.focus();
    }
  };

  const insertPlaceholderIntoSubject = (token: string) => {
    // If parent provided a handler via props, call it
    try {
      if (typeof onInsertIntoSubject === "function") {
        try {
          const handled = onInsertIntoSubject(token);
          if (handled) return true;
        } catch (e) {
          // continue to fallback
        }
      }
    } catch (e) {
      // ignore
    }

    // Fallback: try to modify DOM directly (not preferred)
    if (!subjectRef || !subjectRef.current) return false;
    const ref = subjectRef.current as HTMLInputElement;
    try {
      const start = (ref.selectionStart ?? ref.value.length) as number;
      const end = (ref.selectionEnd ?? start) as number;
      const v = ref.value || "";
      const nv = v.slice(0, start) + token + v.slice(end);
      // Direct DOM update; parent state may be out-of-sync
      ref.value = nv;
      const pos = start + token.length;
      ref.setSelectionRange(pos, pos);
      ref.focus();
      const ev = new Event("input", { bubbles: true });
      ref.dispatchEvent(ev);
      return true;
    } catch (e) {
      return false;
    }
  };

  const insertPlaceholderIntoEditor = (label: string, dataKey: string) => {
    const span = document.createElement("span");
    span.setAttribute("data-placeholder", dataKey);
    span.setAttribute("contenteditable", "false");
    span.style.background = "#fff3cd";
    span.style.border = "1px solid #ffeeba";
    span.style.padding = "2px 6px";
    span.style.borderRadius = "4px";
    span.style.margin = "0 2px";
    span.style.fontSize = "0.95em";
    span.style.display = "inline-block";
    span.style.userSelect = "none";
    span.textContent = label;

    try {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0) {
        const range = sel.getRangeAt(0);
        range.deleteContents();
        range.insertNode(span);
        const newRange = document.createRange();
        newRange.setStartAfter(span);
        newRange.collapse(true);
        sel.removeAllRanges();
        sel.addRange(newRange);
      } else {
        editorRef.current?.appendChild(span);
      }
    } catch (e) {
      editorRef.current?.appendChild(span);
    }
    if (editorRef.current) onChange(editorRef.current.innerHTML);
  };

  const execCommand = (command: string, val: any = null) => {
    if (command === "createLink") {
      document.execCommand("createLink", false, val);
      if (editorRef.current) onChange(editorRef.current.innerHTML);
      return;
    }

    if (command === "insertPlaceholder") {
      const key = String(val || "").toLowerCase();
      const labelMap: Record<string, string> = {
        name: "{{氏名}}",
        position: "{{職種}}",
        employer: "{{会社名}}",
      };
      const dataMap: Record<string, string> = {
        name: "applicant_name",
        position: "job_title",
        employer: "employer_name",
      };
      const label = labelMap[key] || `{{${key}}}`;
      const dataKey = dataMap[key] || key;
      // Decide target explicitly to avoid inserting into unrelated DOM nodes.
      try {
        // 1) Subject focused -> insert into subject
        if (
          subjectRef &&
          subjectRef.current &&
          document.activeElement === subjectRef.current
        ) {
          const tokenMap: Record<string, string> = {
            name: "{{applicant_name}}",
            position: "{{job_title}}",
            employer: "{{employer_name}}",
          };
          const token = tokenMap[dataKey] || `{{${dataKey}}}`;
          const ok = insertPlaceholderIntoSubject(token);
          if (ok) return;
        }

        // 2) If selection is inside editor, insert at selection
        const sel = window.getSelection();
        const anchor = sel && sel.anchorNode ? sel.anchorNode : null;
        if (anchor && editorRef.current && editorRef.current.contains(anchor)) {
          insertPlaceholderIntoEditor(label, dataKey);
          return;
        }

        // 3) Otherwise, focus editor and append at end
        if (editorRef.current) {
          editorRef.current.focus();
          // ensure selection is at end
          try {
            const range = document.createRange();
            range.selectNodeContents(editorRef.current);
            range.collapse(false);
            const s = window.getSelection();
            s?.removeAllRanges();
            s?.addRange(range);
          } catch (e) {}
          insertPlaceholderIntoEditor(label, dataKey);
          return;
        }
      } catch (e) {
        // final fallback -> insert into editor DOM if available
      }

      insertPlaceholderIntoEditor(label, dataKey);
      return;
    }

    // default exec for bold/italic/underline
    document.execCommand(command, false, val);
    if (editorRef.current) onChange(editorRef.current.innerHTML);
  };

  // small link dialog handler UI
  const renderLinkDialog = () => {
    if (!showLinkDialog) return null;
    return (
      <div
        style={{ padding: 8, borderTop: "1px solid #eee", background: "#fff" }}
      >
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            autoFocus
            value={linkUrl}
            onChange={(e) => setLinkUrl(e.target.value)}
            placeholder="https://..."
            style={{
              flex: 1,
              padding: 8,
              border: "1px solid #ddd",
              borderRadius: 4,
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                if (linkUrl.trim()) {
                  try {
                    restoreSelection();
                  } catch {}
                  execCommand("createLink", linkUrl.trim());
                }
                setLinkUrl("");
                setShowLinkDialog(false);
              } else if (e.key === "Escape") {
                setLinkUrl("");
                setShowLinkDialog(false);
              }
            }}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={() => {
                setLinkUrl("");
                setShowLinkDialog(false);
              }}
              style={{
                padding: "8px 12px",
                borderRadius: 4,
                border: "1px solid #ddd",
                background: "#f8f9fa",
              }}
            >
              キャンセル
            </button>
            <button
              onClick={() => {
                if (linkUrl.trim()) {
                  try {
                    restoreSelection();
                  } catch {}
                  execCommand("createLink", linkUrl.trim());
                }
                setLinkUrl("");
                setShowLinkDialog(false);
              }}
              disabled={!linkUrl.trim()}
              style={{
                padding: "8px 12px",
                borderRadius: 4,
                border: "none",
                background: linkUrl.trim() ? "#333" : "#ccc",
                color: "#fff",
              }}
            >
              挿入
            </button>
          </div>
        </div>
      </div>
    );
  };

  const handleInput = () => {
    if (editorRef.current && !isComposingRef.current)
      onChange(editorRef.current.innerHTML);
  };

  useEffect(() => {
    const el = editorRef.current;
    if (!el) return;
    const isFocused = document.activeElement === el;
    if (isComposingRef.current || isFocused) return;
    const domHtml = el.innerHTML || "";
    const newHtml = value || "";
    if (domHtml === newHtml) return;
    el.innerHTML = newHtml;
  }, [value]);

  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 4 }}>
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
          onMouseDown={(e) => {
            e.preventDefault();
            execCommand("bold");
          }}
          title="太字"
          style={{
            border: "none",
            background: "transparent",
            padding: "4px 8px",
            cursor: "pointer",
            borderRadius: 2,
            fontSize: 14,
            fontWeight: "bold",
          }}
        >
          B
        </button>
        <button
          type="button"
          onMouseDown={(e) => {
            e.preventDefault();
            execCommand("italic");
          }}
          title="斜体"
          style={{
            border: "none",
            background: "transparent",
            padding: "4px 8px",
            cursor: "pointer",
            borderRadius: 2,
            fontSize: 14,
            fontStyle: "italic",
          }}
        >
          I
        </button>
        <button
          type="button"
          onMouseDown={(e) => {
            e.preventDefault();
            execCommand("underline");
          }}
          title="下線"
          style={{
            border: "none",
            background: "transparent",
            padding: "4px 8px",
            cursor: "pointer",
            borderRadius: 2,
            fontSize: 14,
            textDecoration: "underline",
          }}
        >
          U
        </button>
        <button
          type="button"
          onMouseDown={(e) => {
            e.preventDefault();
            saveSelection();
            setShowLinkDialog(true);
          }}
          title="リンク"
          style={{
            border: "none",
            background: "transparent",
            padding: "4px 8px",
            cursor: "pointer",
            borderRadius: 2,
            fontSize: 14,
          }}
        >
          🔗
        </button>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <button
            type="button"
            onMouseDown={(e) => {
              e.preventDefault();
              execCommand("insertPlaceholder", "name");
            }}
            title="氏名を挿入"
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
            }}
          >
            氏名
          </button>
          <button
            type="button"
            onMouseDown={(e) => {
              e.preventDefault();
              execCommand("insertPlaceholder", "position");
            }}
            title="職種を挿入"
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
            }}
          >
            職種
          </button>
          <button
            type="button"
            onMouseDown={(e) => {
              e.preventDefault();
              execCommand("insertPlaceholder", "employer");
            }}
            title="会社名を挿入"
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
            }}
          >
            会社名
          </button>
        </div>
      </div>

      <div
        ref={editorRef}
        contentEditable
        onInput={handleInput}
        onCompositionStart={() => (isComposingRef.current = true)}
        onCompositionEnd={() => {
          isComposingRef.current = false;
          if (editorRef.current) onChange(editorRef.current.innerHTML);
        }}
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
      `}</style>
    </div>
  );
};

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
  const subjectRef = useRef<HTMLInputElement | null>(null);
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
      sms: {
        enabled: boolean;
        text: string;
        sendMode?: "immediate" | "scheduled" | "delayed"; // 即时/定时/预约
        scheduledTime?: string; // 定时发送时间 (HH:mm格式)
        delayMinutes?: number; // 预约发送延迟分钟数
      };
      mail: {
        enabled: boolean;
        subject: string;
        body: string;
        sendMode?: "immediate" | "scheduled" | "delayed"; // 即时/定时/预约
        scheduledTime?: string; // 定时发送时间 (HH:mm格式)
        delayMinutes?: number; // 预约发送延迟分钟数
      };
    };
  };
  const [siteType, setSiteType] = useState<SiteType>("jobbox");
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
      sms: {
        enabled: true,
        text: "",
        sendMode: "immediate",
        scheduledTime: "09:00",
        delayMinutes: 30,
      },
      mail: {
        enabled: false,
        subject: "",
        body: "",
        sendMode: "immediate",
        scheduledTime: "09:00",
        delayMinutes: 30,
      },
    },
  });

  // Raw input state for delayed minutes to allow temporary empty values during typing
  const [smsDelayInput, setSmsDelayInput] = useState<string>("30");
  const [mailDelayInput, setMailDelayInput] = useState<string>("30");

  // Keep raw inputs in sync when segDraft changes (e.g., editing an existing segment)
  useEffect(() => {
    const smsVal = segDraft.actions?.sms?.delayMinutes;
    setSmsDelayInput(
      smsVal === undefined || smsVal === null ? "" : String(smsVal)
    );
    const mailVal = segDraft.actions?.mail?.delayMinutes;
    setMailDelayInput(
      mailVal === undefined || mailVal === null ? "" : String(mailVal)
    );
  }, [
    segDraft.actions?.sms?.delayMinutes,
    segDraft.actions?.mail?.delayMinutes,
  ]);

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
  }, [siteType]);

  async function loadSetting() {
    const user = await waitForAuthReady();
    if (!user) return;
    try {
      const db = getFirestore();
      const uid = (user as any).uid;
      const settingsCollection =
        siteType === "jobbox" ? "target_settings" : "engage_target_settings";
      const docRef = doc(db, "accounts", uid, settingsCollection, "settings");
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
      const segmentsCollection =
        siteType === "jobbox" ? "target_segments" : "engage_target_segments";
      const coll = collection(db, "accounts", uid, segmentsCollection);
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

      // SMS または メール のどちらか一つは選択必須
      if (!segDraft.actions.sms.enabled && !segDraft.actions.mail.enabled) {
        setSaveMessage({
          type: "error",
          text: "条件に不足があるため保存できません",
        });
        return;
      }

      // Validate delayed minutes upper bound (1-1440)
      if (
        segDraft.actions.sms.enabled &&
        segDraft.actions.sms.sendMode === "delayed"
      ) {
        const v = segDraft.actions.sms.delayMinutes ?? 0;
        if (v > 1440 || v < 1) {
          setSaveMessage({
            type: "error",
            text: "SMSの予約送信の時間は1〜1440分の範囲で指定してください。",
          });
          return;
        }
      }
      if (
        segDraft.actions.mail.enabled &&
        segDraft.actions.mail.sendMode === "delayed"
      ) {
        const v = segDraft.actions.mail.delayMinutes ?? 0;
        if (v > 1440 || v < 1) {
          setSaveMessage({
            type: "error",
            text: "メールの予約送信の時間は1〜1440分の範囲で指定してください。",
          });
          return;
        }
      }

      console.log("Saving segment:", segDraft);

      // 测试基本的写权限
      const segmentsCollection =
        siteType === "jobbox" ? "target_segments" : "engage_target_segments";
      console.log(
        "Testing write permission to path: accounts/" +
          uid +
          "/" +
          segmentsCollection
      );

      // Prepare payloads without undefined fields (Firestore rejects undefined)
      const smsPayload: any = {
        enabled: !!segDraft.actions.sms.enabled,
        text: segDraft.actions.sms.text,
        sendMode: segDraft.actions.sms.sendMode || "immediate",
        scheduledTime: segDraft.actions.sms.scheduledTime || "09:00",
      };
      if (segDraft.actions.sms.sendMode === "delayed") {
        const v = segDraft.actions.sms.delayMinutes as any;
        if (typeof v === "number" && !isNaN(v)) smsPayload.delayMinutes = v;
      }

      const mailPayload: any = {
        enabled: !!segDraft.actions.mail.enabled,
        subject: segDraft.actions.mail.subject,
        body: serializePlaceholdersFromHtml(segDraft.actions.mail.body || ""),
        sendMode: segDraft.actions.mail.sendMode || "immediate",
        scheduledTime: segDraft.actions.mail.scheduledTime || "09:00",
      };
      if (segDraft.actions.mail.sendMode === "delayed") {
        const v = segDraft.actions.mail.delayMinutes as any;
        if (typeof v === "number" && !isNaN(v)) mailPayload.delayMinutes = v;
      }

      // Update if editing existing segment (has id), else add new
      if (segDraft.id) {
        console.log("Updating existing segment:", segDraft.id);
        await updateDoc(
          doc(db, "accounts", uid, segmentsCollection, segDraft.id),
          {
            title: segDraft.title.trim(),
            enabled: !!segDraft.enabled,
            priority: Number(segDraft.priority) || 0,
            conditions: segDraft.conditions,
            actions: { sms: smsPayload, mail: mailPayload },
            updatedAt: serverTimestamp(),
          }
        );
      } else {
        console.log("Creating new segment");
        const coll = collection(db, "accounts", uid, segmentsCollection);
        await addDoc(coll, {
          title: segDraft.title.trim(),
          enabled: !!segDraft.enabled,
          priority: Number(segDraft.priority) || 0,
          conditions: segDraft.conditions,
          actions: { sms: smsPayload, mail: mailPayload },
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
          sms: {
            enabled: true,
            text: "",
            sendMode: "immediate",
            scheduledTime: "09:00",
          },
          mail: {
            enabled: false,
            subject: "",
            body: "",
            sendMode: "immediate",
            scheduledTime: "09:00",
          },
        },
      });
      setSegFormOpen(false);
      loadSegments();
      setSaveMessage({ type: "success", text: " 保存しました！" });
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
      const segmentsCollection =
        siteType === "jobbox" ? "target_segments" : "engage_target_segments";
      await deleteDoc(doc(db, "accounts", uid, segmentsCollection, id));
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
    // convert stored token body (if any) into editor-friendly HTML with placeholder spans
    const converted = { ...seg } as any;
    try {
      if (converted.actions?.mail?.body) {
        converted.actions.mail.body = tokensToHtml(converted.actions.mail.body);
      }
    } catch (e) {
      // ignore
    }
    // Ensure delayMinutes has a default value if not present
    if (
      converted.actions?.sms &&
      converted.actions.sms.delayMinutes === undefined
    ) {
      converted.actions.sms.delayMinutes = 30;
    }
    if (
      converted.actions?.mail &&
      converted.actions.mail.delayMinutes === undefined
    ) {
      converted.actions.mail.delayMinutes = 30;
    }
    setSegDraft({ ...converted });
    setSegFormOpen(true);
  }

  async function toggleSegment(id?: string, enabled?: boolean) {
    if (!id) return;
    try {
      const user = await waitForAuthReady();
      if (!user) throw new Error("未ログインです。ログインしてください。");
      const db = getFirestore();
      const uid = (user as any).uid;
      const segmentsCollection =
        siteType === "jobbox" ? "target_segments" : "engage_target_segments";
      await updateDoc(doc(db, "accounts", uid, segmentsCollection, id), {
        enabled: !enabled,
        updatedAt: Date.now(),
      });
      loadSegments();
    } catch (e) {
      console.error("toggleSegment error", e);
    }
  }

  // Move a segment up/down using a batch write that reassigns priority to every item
  async function moveSegment(id: string, direction: number) {
    if (!id) return;
    try {
      const idx = segments.findIndex((x) => x.id === id);
      if (idx === -1) return;
      const newIndex = idx + direction;
      if (newIndex < 0 || newIndex >= segments.length) return;

      // Build new order by swapping positions
      const newOrder = [...segments];
      const tmp = newOrder[idx];
      newOrder[idx] = newOrder[newIndex];
      newOrder[newIndex] = tmp;

      // Optimistic UI update
      setSegments(newOrder.map((seg, i) => ({ ...(seg as any), priority: i })));

      const user = await waitForAuthReady();
      if (!user) throw new Error("未ログインです。ログインしてください。");
      const db = getFirestore();
      const uid = (user as any).uid;

      // Use batch to atomically write new priorities for all items in the list
      const segmentsCollection =
        siteType === "jobbox" ? "target_segments" : "engage_target_segments";
      const batch = writeBatch(db);
      newOrder.forEach((seg, i) => {
        if (!seg.id) return;
        const ref = doc(db, "accounts", uid, segmentsCollection, seg.id);
        batch.update(ref, { priority: i, updatedAt: serverTimestamp() } as any);
      });

      await batch.commit();

      // Reload to ensure alignment with server (and pick up any server-side ordering)
      loadSegments();
    } catch (e) {
      console.error("moveSegment (batch) error", e);
      // fallback: refresh from server
      loadSegments();
    }
  }

  function moveSegmentUp(id: string) {
    return moveSegment(id, -1);
  }

  function moveSegmentDown(id: string) {
    return moveSegment(id, 1);
  }

  // Derived validation flags for delayed minutes inputs
  const smsDelayNum = parseInt(smsDelayInput || "", 10);
  const mailDelayNum = parseInt(mailDelayInput || "", 10);
  const smsDelayInvalid =
    segDraft.actions.sms.enabled &&
    segDraft.actions.sms.sendMode === "delayed" &&
    (isNaN(smsDelayNum) || smsDelayNum > 1440 || smsDelayNum < 1);
  const mailDelayInvalid =
    segDraft.actions.mail.enabled &&
    segDraft.actions.mail.sendMode === "delayed" &&
    (isNaN(mailDelayNum) || mailDelayNum > 1440 || mailDelayNum < 1);
  const hasInvalidDelays = smsDelayInvalid || mailDelayInvalid;

  return (
    <div style={{ padding: 28 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12 }}>
        対象設定
      </h2>
      <p style={{ marginBottom: 16 }}>
        RoMeALLが対象とする応募者を設定 / 管理することができます。
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

      {/* Segments (多条件分组) manager - 完全按照截图重新设计 */}
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
                fontWeight: 700,
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
                fontWeight: 700,
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
                fontWeight: 700,
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
                    fontWeight: 700,
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
                    fontWeight: 700,
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
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 8,
                }}
              >
                <div style={{ fontSize: 13, color: "#666", fontWeight: 700 }}>
                  SMS本文
                </div>
              </div>

              {/* SMS 发送模式选择 */}
              <div style={{ marginBottom: 12 }}>
                <label
                  style={{
                    display: "block",
                    marginBottom: 8,
                    fontSize: 14,
                    fontWeight: 700,
                    color: "#333",
                  }}
                >
                  SMS送信モード
                </label>
                <div style={{ display: "flex", gap: 16 }}>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="radio"
                      checked={segDraft.actions.sms.sendMode === "immediate"}
                      onChange={() =>
                        setSegDraft((s) => ({
                          ...s,
                          actions: {
                            ...s.actions,
                            sms: { ...s.actions.sms, sendMode: "immediate" },
                          },
                        }))
                      }
                      style={{ marginRight: 6 }}
                    />
                    即時送信
                  </label>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="radio"
                      checked={segDraft.actions.sms.sendMode === "scheduled"}
                      onChange={() =>
                        setSegDraft((s) => ({
                          ...s,
                          actions: {
                            ...s.actions,
                            sms: { ...s.actions.sms, sendMode: "scheduled" },
                          },
                        }))
                      }
                      style={{ marginRight: 6 }}
                    />
                    時刻送信
                  </label>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="radio"
                      checked={segDraft.actions.sms.sendMode === "delayed"}
                      onChange={() =>
                        setSegDraft((s) => ({
                          ...s,
                          actions: {
                            ...s.actions,
                            sms: { ...s.actions.sms, sendMode: "delayed" },
                          },
                        }))
                      }
                      style={{ marginRight: 6 }}
                    />
                    予約送信
                  </label>
                </div>
              </div>

              {/* 定时发送时间选择 */}
              {segDraft.actions.sms.sendMode === "scheduled" && (
                <div style={{ marginBottom: 12 }}>
                  <label
                    style={{
                      display: "block",
                      marginBottom: 8,
                      fontSize: 14,
                      fontWeight: 700,
                      color: "#333",
                    }}
                  >
                    送信時刻
                  </label>
                  <input
                    type="time"
                    value={segDraft.actions.sms.scheduledTime || "09:00"}
                    onChange={(e) =>
                      setSegDraft((s) => ({
                        ...s,
                        actions: {
                          ...s.actions,
                          sms: {
                            ...s.actions.sms,
                            scheduledTime: e.target.value,
                          },
                        },
                      }))
                    }
                    style={{
                      padding: "8px 12px",
                      border: "1px solid #ddd",
                      borderRadius: 4,
                      fontSize: 14,
                    }}
                  />
                  <div style={{ marginTop: 4, fontSize: 12, color: "#666" }}>
                    ※ 毎日この時刻に送信されます
                  </div>
                </div>
              )}

              {/* 预约发送延迟分钟数选择 */}
              {segDraft.actions.sms.sendMode === "delayed" && (
                <div style={{ marginBottom: 12 }}>
                  <label
                    style={{
                      display: "block",
                      marginBottom: 8,
                      fontSize: 14,
                      fontWeight: 700,
                      color: "#333",
                    }}
                  >
                    送信までの時間（分）
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="1440"
                    value={smsDelayInput}
                    onChange={(e) => {
                      const raw = e.target.value;
                      setSmsDelayInput(raw);
                      const num = parseInt(raw, 10);
                      setSegDraft((s) => ({
                        ...s,
                        actions: {
                          ...s.actions,
                          sms: {
                            ...s.actions.sms,
                            delayMinutes: isNaN(num) ? (undefined as any) : num,
                          },
                        },
                      }));
                    }}
                    style={{
                      padding: "8px 12px",
                      border: "1px solid #ddd",
                      borderRadius: 4,
                      fontSize: 14,
                      width: "120px",
                    }}
                  />
                  <span style={{ marginLeft: 8, fontSize: 14, color: "#666" }}>
                    分後
                  </span>
                  <span style={{ marginLeft: 12, fontSize: 12, color: "#888" }}>
                    （最小1分、最大1440分まで指定可能）
                  </span>
                  {(() => {
                    const num = parseInt(smsDelayInput || "", 10);
                    const invalid =
                      segDraft.actions.sms.enabled &&
                      segDraft.actions.sms.sendMode === "delayed" &&
                      (isNaN(num) || num < 1 || num > 1440);
                    return invalid ? (
                      <div
                        style={{ marginTop: 6, fontSize: 12, color: "#d9534f" }}
                      >
                        1440分を超える値は指定できません（1〜1440）。
                      </div>
                    ) : null;
                  })()}
                </div>
              )}

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
              <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                <button
                  onClick={() => {
                    const token = "{{applicant_name}}";
                    setSegDraft((s) => ({
                      ...s,
                      actions: {
                        ...s.actions,
                        sms: {
                          ...s.actions.sms,
                          text: (s.actions.sms.text || "") + token,
                        },
                      },
                    }));
                  }}
                  style={{
                    padding: "6px 8px",
                    borderRadius: 4,
                    border: "1px solid #ddd",
                    background: "#fff",
                  }}
                >
                  氏名
                </button>
                <button
                  onClick={() => {
                    // use canonical key matching Firestore/jobbox parsing
                    const token = "{{job_title}}";
                    setSegDraft((s) => ({
                      ...s,
                      actions: {
                        ...s.actions,
                        sms: {
                          ...s.actions.sms,
                          text: (s.actions.sms.text || "") + token,
                        },
                      },
                    }));
                  }}
                  style={{
                    padding: "6px 8px",
                    borderRadius: 4,
                    border: "1px solid #ddd",
                    background: "#fff",
                  }}
                >
                  職種
                </button>
                <button
                  onClick={() => {
                    // use canonical key matching mail template tokens (employer_name)
                    const token = "{{employer_name}}";
                    setSegDraft((s) => ({
                      ...s,
                      actions: {
                        ...s.actions,
                        sms: {
                          ...s.actions.sms,
                          text: (s.actions.sms.text || "") + token,
                        },
                      },
                    }));
                  }}
                  style={{
                    padding: "6px 8px",
                    borderRadius: 4,
                    border: "1px solid #ddd",
                    background: "#fff",
                  }}
                >
                  会社名
                </button>
              </div>
            </div>
          )}

          {/* メール内容 */}
          {segDraft.actions.mail.enabled && (
            <div style={{ marginBottom: 20 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 8,
                }}
              >
                <div style={{ fontSize: 13, color: "#666", fontWeight: 700 }}>
                  メール本文
                </div>
              </div>

              {/* MAIL 发送模式选择 */}
              <div style={{ marginBottom: 12 }}>
                <label
                  style={{
                    display: "block",
                    marginBottom: 8,
                    fontSize: 14,
                    fontWeight: 700,
                    color: "#333",
                  }}
                >
                  メール送信モード
                </label>
                <div style={{ display: "flex", gap: 16 }}>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="radio"
                      checked={segDraft.actions.mail.sendMode === "immediate"}
                      onChange={() =>
                        setSegDraft((s) => ({
                          ...s,
                          actions: {
                            ...s.actions,
                            mail: { ...s.actions.mail, sendMode: "immediate" },
                          },
                        }))
                      }
                      style={{ marginRight: 6 }}
                    />
                    即時送信
                  </label>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="radio"
                      checked={segDraft.actions.mail.sendMode === "scheduled"}
                      onChange={() =>
                        setSegDraft((s) => ({
                          ...s,
                          actions: {
                            ...s.actions,
                            mail: { ...s.actions.mail, sendMode: "scheduled" },
                          },
                        }))
                      }
                      style={{ marginRight: 6 }}
                    />
                    時刻送信
                  </label>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      cursor: "pointer",
                    }}
                  >
                    <input
                      type="radio"
                      checked={segDraft.actions.mail.sendMode === "delayed"}
                      onChange={() =>
                        setSegDraft((s) => ({
                          ...s,
                          actions: {
                            ...s.actions,
                            mail: { ...s.actions.mail, sendMode: "delayed" },
                          },
                        }))
                      }
                      style={{ marginRight: 6 }}
                    />
                    予約送信
                  </label>
                </div>
              </div>

              {/* 定时发送时间选择 */}
              {segDraft.actions.mail.sendMode === "scheduled" && (
                <div style={{ marginBottom: 12 }}>
                  <label
                    style={{
                      display: "block",
                      marginBottom: 8,
                      fontSize: 14,
                      fontWeight: 700,
                      color: "#333",
                    }}
                  >
                    送信時刻
                  </label>
                  <input
                    type="time"
                    value={segDraft.actions.mail.scheduledTime || "09:00"}
                    onChange={(e) =>
                      setSegDraft((s) => ({
                        ...s,
                        actions: {
                          ...s.actions,
                          mail: {
                            ...s.actions.mail,
                            scheduledTime: e.target.value,
                          },
                        },
                      }))
                    }
                    style={{
                      padding: "8px 12px",
                      border: "1px solid #ddd",
                      borderRadius: 4,
                      fontSize: 14,
                    }}
                  />
                  <div style={{ marginTop: 4, fontSize: 12, color: "#666" }}>
                    ※ 毎日この時刻に送信されます
                  </div>
                </div>
              )}

              {/* MAIL预约发送延迟分钟数选择 */}
              {segDraft.actions.mail.sendMode === "delayed" && (
                <div style={{ marginBottom: 12 }}>
                  <label
                    style={{
                      display: "block",
                      marginBottom: 8,
                      fontSize: 14,
                      fontWeight: 700,
                      color: "#333",
                    }}
                  >
                    送信までの時間（分）
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="1440"
                    value={mailDelayInput}
                    onChange={(e) => {
                      const raw = e.target.value;
                      setMailDelayInput(raw);
                      const num = parseInt(raw, 10);
                      setSegDraft((s) => ({
                        ...s,
                        actions: {
                          ...s.actions,
                          mail: {
                            ...s.actions.mail,
                            delayMinutes: isNaN(num) ? (undefined as any) : num,
                          },
                        },
                      }));
                    }}
                    style={{
                      padding: "8px 12px",
                      border: "1px solid #ddd",
                      borderRadius: 4,
                      fontSize: 14,
                      width: "120px",
                    }}
                  />
                  <span style={{ marginLeft: 8, fontSize: 14, color: "#666" }}>
                    分後
                  </span>
                  <span style={{ marginLeft: 12, fontSize: 12, color: "#888" }}>
                    （最小1分、最大1440分まで指定可能）
                  </span>
                  {(() => {
                    const num = parseInt(mailDelayInput || "", 10);
                    const invalid =
                      segDraft.actions.mail.enabled &&
                      segDraft.actions.mail.sendMode === "delayed" &&
                      (isNaN(num) || num < 1 || num > 1440);
                    return invalid ? (
                      <div
                        style={{ marginTop: 6, fontSize: 12, color: "#d9534f" }}
                      >
                        1440分を超える値は指定できません（1〜1440）。
                      </div>
                    ) : null;
                  })()}
                </div>
              )}

              <div
                style={{
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                  marginBottom: 8,
                }}
              >
                <input
                  ref={subjectRef}
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
                    flex: 1,
                    padding: "8px 12px",
                    border: "1px solid #ddd",
                    borderRadius: 4,
                    fontSize: 14,
                    boxSizing: "border-box",
                  }}
                />
                <div style={{ display: "flex", gap: 6 }}>
                  {/* Subject buttons removed: use editor toolbar buttons which now insert into subject when it has focus */}
                </div>
              </div>

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
                onInsertIntoSubject={(token: string) => {
                  // Compute caret pos (if available), update React state, then restore caret
                  let start: number | null = null;
                  let end: number | null = null;
                  try {
                    const ref = subjectRef.current as HTMLInputElement | null;
                    if (ref) {
                      start = (ref.selectionStart ??
                        ref.value.length) as number;
                      end = (ref.selectionEnd ?? start) as number;
                    }
                  } catch (e) {}

                  setSegDraft((s) => {
                    const cur = s.actions.mail.subject || "";
                    let newVal = cur + token;
                    try {
                      const ref = subjectRef.current as HTMLInputElement | null;
                      if (ref && start !== null && end !== null) {
                        const v = ref.value || "";
                        newVal = v.slice(0, start) + token + v.slice(end);
                      }
                    } catch (e) {}
                    return {
                      ...s,
                      actions: {
                        ...s.actions,
                        mail: { ...s.actions.mail, subject: newVal },
                      },
                    };
                  });

                  // Restore caret after React has applied the state change
                  if (start !== null) {
                    setTimeout(() => {
                      try {
                        const ref =
                          subjectRef.current as HTMLInputElement | null;
                        if (ref) {
                          const pos = start! + token.length;
                          ref.setSelectionRange(pos, pos);
                          ref.focus();
                        }
                      } catch (e) {}
                    }, 0);
                  }
                  return true;
                }}
                subjectRef={subjectRef}
                placeholder="お忙しい中ご応募ありがとうございます。xxx株式会社です。下記よりLINE登録をお願いいたします！https://line..."
              />
            </div>
          )}

          {/* 保存ボタン */}
          <div style={{ textAlign: "center", marginTop: 24 }}>
            <button
              onClick={saveSegment}
              disabled={hasInvalidDelays}
              style={{
                background: hasInvalidDelays ? "#ccc" : "#333",
                color: "#fff",
                border: "none",
                borderRadius: 4,
                padding: "12px 40px",
                fontSize: 14,
                fontWeight: 500,
                cursor: hasInvalidDelays ? "not-allowed" : "pointer",
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
                  <div
                    style={{ display: "flex", gap: 8, alignItems: "center" }}
                  >
                    <button
                      type="button"
                      onClick={() => moveSegmentUp(s.id)}
                      disabled={segments.findIndex((x) => x.id === s.id) === 0}
                      title="上へ移動"
                      className="seg-arrow-btn"
                    >
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <path d="M6 15l6-6 6 6" />
                      </svg>
                    </button>

                    <button
                      type="button"
                      onClick={() => moveSegmentDown(s.id)}
                      disabled={
                        segments.findIndex((x) => x.id === s.id) ===
                        segments.length - 1
                      }
                      title="下へ移動"
                      className="seg-arrow-btn"
                    >
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <path d="M6 9l6 6 6-6" />
                      </svg>
                    </button>

                    <button
                      onClick={() => editSegment(s)}
                      className="seg-ctrl-btn"
                      title="編集"
                    >
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                      </svg>
                    </button>
                    <button
                      onClick={() => showDeleteDialog(s)}
                      className="seg-ctrl-btn"
                      title="削除"
                    >
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                      >
                        <polyline points="3,6 5,6 21,6" />
                        <path d="M19,6V20a2,2 0 0,1 -2,2H7a2,2 0 0,1 -2,-2V6M8,6V4a2,2 0 0,1 2,-2h4a2,2 0 0,1 2,2V6" />
                        <line x1="10" y1="11" x2="10" y2="17" />
                        <line x1="14" y1="11" x2="14" y2="17" />
                      </svg>
                    </button>
                  </div>
                </div>

                {/* 条件の詳細表示 */}
                <div style={{ fontSize: 13, color: "#666", marginBottom: 8 }}>
                  <div style={{ marginBottom: 4 }}>
                    <strong>対象:</strong>
                    {["kanji", "katakana", "hiragana", "alpha"]
                      .filter((k) => (s.conditions.nameTypes as any)[k])
                      .map(
                        (k) =>
                          ((
                            {
                              kanji: "漢字名",
                              katakana: "カタカナ名",
                              hiragana: "ひらがな名",
                              alpha: "アルファベット名",
                            } as any
                          )[k])
                      )
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
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                    {s.actions.sms.enabled && (
                      <div
                        style={{
                          background: "#e3f2fd",
                          color: "#1976d2",
                          padding: "4px 8px",
                          borderRadius: 12,
                          fontSize: 11,
                          fontWeight: 500,
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        SMS送信
                        {s.actions.sms.sendMode === "scheduled" && (
                          <span
                            style={{
                              background: "#1976d2",
                              color: "#fff",
                              padding: "2px 6px",
                              borderRadius: 8,
                              fontSize: 10,
                              marginLeft: 4,
                            }}
                          >
                            ⏰ {s.actions.sms.scheduledTime || "定時"}
                          </span>
                        )}
                        {s.actions.sms.sendMode === "delayed" && (
                          <span
                            style={{
                              background: "#ff9800",
                              color: "#fff",
                              padding: "2px 6px",
                              borderRadius: 8,
                              fontSize: 10,
                              marginLeft: 4,
                            }}
                          >
                            ⏱ {s.actions.sms.delayMinutes || 30}分後
                          </span>
                        )}
                      </div>
                    )}
                    {s.actions.mail.enabled && (
                      <div
                        style={{
                          background: "#f3e5f5",
                          color: "#7b1fa2",
                          padding: "4px 8px",
                          borderRadius: 12,
                          fontSize: 11,
                          fontWeight: 500,
                          display: "flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        メール送信
                        {s.actions.mail.sendMode === "scheduled" && (
                          <span
                            style={{
                              background: "#7b1fa2",
                              color: "#fff",
                              padding: "2px 6px",
                              borderRadius: 8,
                              fontSize: 10,
                              marginLeft: 4,
                            }}
                          >
                            ⏰ {s.actions.mail.scheduledTime || "定時"}
                          </span>
                        )}
                        {s.actions.mail.sendMode === "delayed" && (
                          <span
                            style={{
                              background: "#ff9800",
                              color: "#fff",
                              padding: "2px 6px",
                              borderRadius: 8,
                              fontSize: 10,
                              marginLeft: 4,
                            }}
                          >
                            ⏱ {s.actions.mail.delayMinutes || 30}分後
                          </span>
                        )}
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
                  background: "rgba(20, 19, 22, 1)",
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
