import { Chip } from "@/components/base/badges/chip";

/** A consistent label for an ETF ticker across pages. */
export function EtfChip({ ticker, className }: { ticker: string; className?: string }) {
  return (
    <Chip variant="caption" color="blue" className={className}>
      {ticker.toUpperCase()}
    </Chip>
  );
}
