"use client";

import React from "react";

interface LogoProps {
  size?: number;
  className?: string;
}

export default function Logo({ size = 48, className = "" }: LogoProps) {
  const s = Math.max(16, size);
  return (
    <svg
      width={s}
      height={s}
      viewBox="0 0 64 64"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-labelledby="romeallLogoTitle"
      className={className}
    >
      <title id="romeallLogoTitle">RoMeALL logo</title>
      <defs>
        <linearGradient id="g1" x1="0" x2="1">
          <stop offset="0" stopColor="#6EE7B7" />
          <stop offset="1" stopColor="#3B82F6" />
        </linearGradient>
      </defs>
      {/* Rounded square background */}
      <rect x="2" y="2" width="60" height="60" rx="12" fill="#0F172A" />

      {/* Robot head / circular mark */}
      <g transform="translate(8,8)">
        <circle cx="24" cy="16" r="12" fill="url(#g1)" />
        {/* eye */}
        <circle cx="24" cy="16" r="4" fill="#0F172A" opacity="0.95" />
        {/* antenna */}
        <rect x="30" y="2" width="2" height="8" rx="1" fill="#9CA3AF" />
      </g>

      {/* stylized R letter to match 'RoMe' branding */}
      <path
        d="M18 44 C18 40 22 36 28 36 H36"
        stroke="#E6EEF8"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
        opacity="0.95"
      />
    </svg>
  );
}
