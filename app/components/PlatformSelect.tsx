"use client";

import React, { useEffect, useRef, useState } from "react";

type Platform = "all" | "jobbox" | "engage";

type Props = {
  value: Platform;
  onChange: (v: Platform) => void;
  className?: string;
  style?: React.CSSProperties;
};

const OPTIONS: { value: Platform; label: string }[] = [
  { value: "all", label: "すべて" },
  { value: "jobbox", label: "求人ボックス" },
  { value: "engage", label: "エンゲージ" },
];

export default function PlatformSelect({
  value,
  onChange,
  className,
  style,
}: Props) {
  const [open, setOpen] = useState(false);
  const [hoverIndex, setHoverIndex] = useState<number>(
    Math.max(
      0,
      OPTIONS.findIndex((o) => o.value === value)
    )
  );

  const btnRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (open) {
      const idx = OPTIONS.findIndex((o) => o.value === value);
      setHoverIndex(idx >= 0 ? idx : 0);
    }
  }, [open, value]);

  useEffect(() => {
    const onDocMouseDown = (e: MouseEvent) => {
      if (!open) return;
      const t = e.target as Node;
      if (btnRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  const current = OPTIONS.find((o) => o.value === value) || OPTIONS[0];

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (
      !open &&
      (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")
    ) {
      e.preventDefault();
      setOpen(true);
      return;
    }
    if (!open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setHoverIndex((i) => Math.min(i + 1, OPTIONS.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHoverIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const opt = OPTIONS[hoverIndex];
      if (opt) {
        onChange(opt.value);
        setOpen(false);
      }
    }
  };

  return (
    <div className="platform-select-wrap" style={style}>
      <button
        ref={btnRef}
        type="button"
        className={
          (className ? className + " " : "") +
          "platform-select" +
          (open ? " is-open" : "")
        }
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={onKeyDown}
      >
        {current.label}
        <span className="platform-select__arrow" aria-hidden></span>
      </button>
      {open && (
        <div
          ref={menuRef}
          className="platform-select__menu"
          role="listbox"
          tabIndex={-1}
        >
          {OPTIONS.map((opt, idx) => {
            const selected = opt.value === value;
            const hovered = idx === hoverIndex;
            return (
              <div
                key={opt.value}
                role="option"
                aria-selected={selected}
                className={
                  "platform-select__option" +
                  (selected ? " is-selected" : "") +
                  (hovered ? " is-hover" : "")
                }
                onMouseEnter={() => setHoverIndex(idx)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                }}
              >
                {opt.label}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
