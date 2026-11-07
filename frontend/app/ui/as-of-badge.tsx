import { Chip } from "@/components/base/badges/chip";

const AGING_AFTER_DAYS = 45;

function ageInDays(isoDate: string, today: Date): number | null {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!parts) return null;
  const then = Date.UTC(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]));
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.floor((now - then) / 86_400_000);
}

/** Shows a disclosure date, and flags it when the holdings are getting old. */
export function AsOfBadge({
  date,
  today = new Date(),
  className,
}: {
  date: string | null | undefined;
  today?: Date;
  className?: string;
}) {
  if (!date) {
    return (
      <Chip variant="caption" color="rose" className={className}>
        Date unknown
      </Chip>
    );
  }
  const age = ageInDays(date, today);
  const aging = age !== null && age > AGING_AFTER_DAYS;
  return (
    <Chip
      variant="caption"
      color={aging ? "yellow" : "neutral"}
      className={className}
      title={age === null ? undefined : `Disclosed ${age} day${age === 1 ? "" : "s"} ago`}
    >
      As of {date}
    </Chip>
  );
}
