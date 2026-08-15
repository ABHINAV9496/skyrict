function Glows() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
    >
      <div
        className="absolute -top-40 left-1/2 h-[480px] w-[820px] -translate-x-1/2 rounded-full opacity-60 blur-3xl"
        style={{
          background: "radial-gradient(closest-side, var(--glow-primary), transparent)",
        }}
      />
      <div
        className="absolute top-1/3 -left-40 h-[420px] w-[420px] rounded-full opacity-40 blur-3xl"
        style={{
          background: "radial-gradient(closest-side, var(--glow-secondary), transparent)",
        }}
      />
      <div
        className="absolute -right-40 bottom-0 h-[420px] w-[480px] rounded-full opacity-40 blur-3xl"
        style={{
          background: "radial-gradient(closest-side, var(--glow-tertiary), transparent)",
        }}
      />
    </div>
  );
}

export { Glows };
