/** Formats a contract fraction of 1 as a percentage, e.g. 0.1234 -> 12.34%. */
export function formatPct(fraction: number, digits = 2): string {
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function Pct({
  value,
  digits = 2,
  className,
}: {
  value: number | null | undefined;
  digits?: number;
  className?: string;
}) {
  const known = typeof value === "number" && Number.isFinite(value);
  return (
    <span className={className} style={{ fontVariantNumeric: "tabular-nums" }}>
      {known ? formatPct(value, digits) : "—"}
    </span>
  );
}
