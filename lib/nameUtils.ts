// Utilities to detect name character scripts
export function hasKanji(s: string): boolean {
  return /[\u4E00-\u9FFF]/.test(s);
}

export function hasKatakana(s: string): boolean {
  return /[\u30A0-\u30FF\u31F0-\u31FF]/.test(s);
}

export function hasHiragana(s: string): boolean {
  return /[\u3040-\u309F]/.test(s);
}

export function hasAlphabet(s: string): boolean {
  return /[A-Za-z]/.test(s);
}

export function detectNameTypes(s: string) {
  return {
    kanji: hasKanji(s),
    katakana: hasKatakana(s),
    hiragana: hasHiragana(s),
    alpha: hasAlphabet(s),
  };
}
