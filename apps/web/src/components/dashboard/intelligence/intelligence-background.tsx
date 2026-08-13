/**
 * Decorative market-analytics chart behind the GMIE home hero. A faded green
 * line/area graph with subtle CSS-animated overlays — a sweeping scan, a
 * trend line that draws itself in, and pulsing markers. Pure decoration:
 * never receives pointer events, and motion is disabled under
 * prefers-reduced-motion.
 */
export function IntelligenceBackground() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 overflow-hidden [mask-image:radial-gradient(ellipse_80%_75%_at_50%_45%,black_30%,transparent_78%)] [-webkit-mask-image:radial-gradient(ellipse_80%_75%_at_50%_45%,black_30%,transparent_78%)]"
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
            x1="0"
            y1={y}
            x2="800"
            y2={y}
            stroke="#34d399"
            strokeOpacity="0.08"
            strokeWidth="1"
          />
        ))}

        <path
          d="M0 240 C90 220 140 250 210 238 S340 190 420 200 S560 160 630 170 S750 130 800 140"
          fill="none"
          stroke="#10b981"
          strokeOpacity="0.28"
          strokeWidth="1.5"
        />
        <path
          d="M0 360 C100 350 160 320 240 330 S380 290 460 300 S600 260 680 270 S780 240 800 250"
          fill="none"
          stroke="#10b981"
          strokeOpacity="0.18"
          strokeWidth="1.5"
        />

        <path
          d="M0 320 C70 300 110 260 170 268 C230 276 260 210 330 218 C400 226 430 150 500 160 C570 170 600 110 670 120 C720 126 760 90 800 100 L800 420 L0 420 Z"
          fill="url(#intel-area)"
        />

        <path
          d="M0 320 C70 300 110 260 170 268 C230 276 260 210 330 218 C400 226 430 150 500 160 C570 170 600 110 670 120 C720 126 760 90 800 100"
          fill="none"
          stroke="#34d399"
          strokeOpacity="0.4"
          strokeWidth="2"
        />

        <path
          className="chart-draw"
          d="M0 320 C70 300 110 260 170 268 C230 276 260 210 330 218 C400 226 430 150 500 160 C570 170 600 110 670 120 C720 126 760 90 800 100"
          fill="none"
          stroke="#34d399"
          strokeOpacity="0.8"
          strokeWidth="2.5"
        />

        {[
          { cx: 170, cy: 268, delay: "0.2s" },
          { cx: 330, cy: 218, delay: "0.9s" },
          { cx: 500, cy: 160, delay: "1.6s" },
          { cx: 670, cy: 120, delay: "2.3s" },
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
