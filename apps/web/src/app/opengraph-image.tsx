import { ImageResponse } from "next/og";

import { site } from "@/config";

export const size = {
  width: 1200,
  height: 630,
};

export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background:
            "radial-gradient(circle at 50% 0%, #114f68 0%, #0a2f3e 55%, #061f29 100%)",
          color: "#f4fafd",
          fontFamily: "Inter, system-ui, sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <svg viewBox="0 0 32 32" width="64" height="64" style={{ display: "flex" }}>
            <defs>
              <linearGradient id="sky-mark" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#aedef1" />
                <stop offset="100%" stopColor="#4cb6e1" />
              </linearGradient>
            </defs>
            <rect width="32" height="32" rx="9" fill="url(#sky-mark)" />
            <g stroke="#0a2f3e" strokeWidth="2.6" strokeLinecap="round">
              <path d="M9 22v-4" />
              <path d="M14 22v-8" />
              <path d="M19 22V11" />
              <path d="M24 22v-13" />
            </g>
            <circle cx="24" cy="9" r="2.1" fill="#0a2f3e" stroke="none" />
          </svg>
          <span
            style={{
              fontSize: 64,
              fontWeight: 700,
              letterSpacing: "-0.02em",
            }}
          >
            {site.name}
          </span>
        </div>
        <div
          style={{
            marginTop: 28,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span
            style={{
              color: "#aedef1",
              fontSize: 24,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
            }}
          >
            AI Business Operating System
          </span>
        </div>
      </div>
    ),
    size,
  );
}
