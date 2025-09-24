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
  const [saved, setSaved] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadSetting();
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
      }
    } catch (e) {
      console.error("load target settings error", e);
    } finally {
      setLoaded(true);
    }
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const user = await waitForAuthReady();
      if (!user) throw new Error("未ログインです。ログインしてください。");
      // validate age ranges
      if (genders.male) {
        if (Number(ageRanges.maleMin) > Number(ageRanges.maleMax)) {
          alert(
            "男性の年齢範囲が不正です。最小値は最大値以下である必要があります。"
          );
          setLoading(false);
          return;
        }
      }
      if (genders.female) {
        if (Number(ageRanges.femaleMin) > Number(ageRanges.femaleMax)) {
          alert(
            "女性の年齢範囲が不正です。最小値は最大値以下である必要があります。"
          );
          setLoading(false);
          return;
        }
      }
      const db = getFirestore();
      const uid = (user as any).uid;
      const docRef = doc(db, "accounts", uid, "target_settings", "settings");
      console.log("Saving target settings for uid=", uid, {
        nameTypes,
        genders,
        ageRanges,
      });
      await setDoc(
        docRef,
        {
          nameTypes,
          genders,
          ageRanges,
          smsTemplateA,
          smsTemplateB,
          updatedAt: Date.now(),
        },
        { merge: true }
      );
      console.log("Saved target settings for uid=", uid);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: any) {
      console.error("save target settings error", e);
      alert(e?.message || "保存に失敗しました。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 28 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, marginBottom: 12 }}>
        対象設定
      </h2>
      <p style={{ marginBottom: 16 }}>
        RPAが対象とする求職者を絞り込む設定です。
      </p>

      <form onSubmit={handleSave} autoComplete="off">
        {/* 短信模板输入区域 */}
        <fieldset style={{ marginBottom: 16, border: "none", padding: 0 }}>
          <legend style={{ fontWeight: 700, marginBottom: 8 }}>
            SMSテンプレート
          </legend>
          <div style={{ marginBottom: 6 }}>
            <label
              style={{ fontWeight: 600, display: "block", marginBottom: 4 }}
            >
              A
            </label>
            <textarea
              value={smsTemplateA}
              onChange={(e) => setSmsTemplateA(e.target.value)}
              rows={3}
              style={{
                width: "100%",
                resize: "vertical",
                fontSize: 15,
                padding: 8,
              }}
              placeholder="A用のSMS内容を入力してください"
            />
          </div>
          <div style={{ marginBottom: 6 }}>
            <label
              style={{ fontWeight: 600, display: "block", marginBottom: 4 }}
            >
              B
            </label>
            <textarea
              value={smsTemplateB}
              onChange={(e) => setSmsTemplateB(e.target.value)}
              rows={3}
              style={{
                width: "100%",
                resize: "vertical",
                fontSize: 15,
                padding: 8,
              }}
              placeholder="B用のSMS内容を入力してください"
            />
          </div>
        </fieldset>

        {/* 既存设置区域 ...existing code... */}
        <fieldset style={{ marginBottom: 12, border: "none", padding: 0 }}>
          <legend style={{ fontWeight: 700, marginBottom: 8 }}>名前</legend>
          <div style={{ marginBottom: 8 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={nameTypes.kanji}
                onChange={(e) =>
                  setNameTypes((s) => ({ ...s, kanji: e.target.checked }))
                }
              />
              漢字名
            </label>
          </div>
          <div style={{ marginBottom: 8 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={nameTypes.katakana}
                onChange={(e) =>
                  setNameTypes((s) => ({ ...s, katakana: e.target.checked }))
                }
              />
              カタカナ名
            </label>
          </div>
          <div style={{ marginBottom: 8 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={nameTypes.hiragana}
                onChange={(e) =>
                  setNameTypes((s) => ({ ...s, hiragana: e.target.checked }))
                }
              />
              ひらがな名
            </label>
          </div>
          <div style={{ marginBottom: 8 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={nameTypes.alpha}
                onChange={(e) =>
                  setNameTypes((s) => ({ ...s, alpha: e.target.checked }))
                }
              />
              アルファベット名
            </label>
          </div>
        </fieldset>

        <fieldset style={{ marginBottom: 12, border: "none", padding: 0 }}>
          <legend style={{ fontWeight: 700, marginBottom: 8 }}>
            性別と年齢
          </legend>
          <div
            style={{
              display: "flex",
              gap: 12,
              alignItems: "center",
              marginBottom: 8,
            }}
          >
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={genders.male}
                onChange={(e) =>
                  setGenders((s) => ({ ...s, male: e.target.checked }))
                }
              />
              男性
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <input
                type="checkbox"
                checked={genders.female}
                onChange={(e) =>
                  setGenders((s) => ({ ...s, female: e.target.checked }))
                }
              />
              女性
            </label>
          </div>

          <div
            style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}
          >
            <div>
              <div style={{ fontWeight: 600 }}>男性の年齢範囲</div>
              <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                <input
                  type="number"
                  min={0}
                  max={150}
                  value={ageRanges.maleMin}
                  disabled={!genders.male}
                  onChange={(e) =>
                    setAgeRanges((s) => ({
                      ...s,
                      maleMin: Number(e.target.value),
                    }))
                  }
                  style={{ width: "100%" }}
                />
                <input
                  type="number"
                  min={0}
                  max={150}
                  value={ageRanges.maleMax}
                  disabled={!genders.male}
                  onChange={(e) =>
                    setAgeRanges((s) => ({
                      ...s,
                      maleMax: Number(e.target.value),
                    }))
                  }
                  style={{ width: "100%" }}
                />
              </div>
            </div>

            <div>
              <div style={{ fontWeight: 600 }}>女性の年齢範囲</div>
              <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                <input
                  type="number"
                  min={0}
                  max={150}
                  value={ageRanges.femaleMin}
                  disabled={!genders.female}
                  onChange={(e) =>
                    setAgeRanges((s) => ({
                      ...s,
                      femaleMin: Number(e.target.value),
                    }))
                  }
                  style={{ width: "100%" }}
                />
                <input
                  type="number"
                  min={0}
                  max={150}
                  value={ageRanges.femaleMax}
                  disabled={!genders.female}
                  onChange={(e) =>
                    setAgeRanges((s) => ({
                      ...s,
                      femaleMax: Number(e.target.value),
                    }))
                  }
                  style={{ width: "100%" }}
                />
              </div>
            </div>
          </div>
        </fieldset>

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
