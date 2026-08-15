/**
 * Decorative market-analytics chart behind the GMIE home hero. A faded green
 * line/area graph with subtle CSS-animated overlays — a sweeping
 * scan, a trend line that draws itself in, and pulsing markers. Pure
 * decoration: never receives pointer events, and motion is disabled under
 * prefers-reduced-motion.
 */
export function IntelligenceBackground() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent),linear-gradient(to_bottom,transparent,black_18%,black_78%,transparent)] [-webkit-mask-image:linear-gradient(to_right,transparent,black_8%,black_92%,transparent),linear-gradient(to_bottom,transparent,black_18%,black_78%,transparent)] [mask-composite:intersect] [-webkit-mask-composite:source-in]"
    >
      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 800 420"
        preserveAspectRatio="xMidYMid slice"
        role="presentation"
      >
        <defs>
          <linearGradient id="intel-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity="0.22" />
            <stop offset="100%" stopColor="#34d399" stopOpacity="0" />
          </linearGradient>
        </defs>

        {[80, 160, 240, 320, 400].map((y) => (
          <line
            key={y}
            x1="32"
            y1={y}
            x2="768"
            y2={y}
            stroke="#34d399"
            strokeOpacity="0.08"
            strokeWidth="1"
          />
        ))}

        <path
          d="M32 240 C115 220 161 250 225 238 S345 190 418 200 S547 160 612 170 S722 130 768 140"
          fill="none"
          stroke="#10b981"
          strokeOpacity="0.28"
          strokeWidth="1.5"
        />
        <path
          d="M32 360 C124 350 179 320 253 330 S382 290 455 300 S584 260 658 270 S750 240 768 250"
          fill="none"
          stroke="#10b981"
          strokeOpacity="0.18"
          strokeWidth="1.5"
        />

        <path
          d="M32 320 C96 300 133 260 188 268 C244 276 271 210 336 218 C400 226 428 150 492 160 C556 170 584 110 648 120 C694 126 731 90 768 100 L768 420 L32 420 Z"
          fill="url(#intel-area)"
        />

        <path
          d="M32 320 C96 300 133 260 188 268 C244 276 271 210 336 218 C400 226 428 150 492 160 C556 170 584 110 648 120 C694 126 731 90 768 100"
          fill="none"
          stroke="#34d399"
          strokeOpacity="0.4"
          strokeWidth="2"
        />

        <path
          className="chart-draw"
          d="M32 320 C96 300 133 260 188 268 C244 276 271 210 336 218 C400 226 428 150 492 160 C556 170 584 110 648 120 C694 126 731 90 768 100"
          fill="none"
          stroke="#34d399"
          strokeOpacity="0.8"
          strokeWidth="2.5"
        />

        {[
          { cx: 188, cy: 268, delay: "0.2s" },
          { cx: 336, cy: 218, delay: "0.9s" },
          { cx: 492, cy: 160, delay: "1.6s" },
          { cx: 648, cy: 120, delay: "2.3s" },
        ].map((dot) => (
          <g key={dot.cx} className="chart-pulse" style={{ animationDelay: dot.delay }}>
            <circle cx={dot.cx} cy={dot.cy} r="8" fill="#34d399" fillOpacity="0.15" />
            <circle cx={dot.cx} cy={dot.cy} r="3" fill="#34d399" fillOpacity="0.9" />
          </g>
        ))}
      </svg>

      <div className="chart-scan" />
    </div>
  );
}
