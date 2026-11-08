// Plain-English helpers for Beginner Guide and Dependencies progress (v3.1 K1, FIX-16, FIX-18, FIX-19).
// Avoids splitting mid-sentence on corporate/country abbreviations like
// "Co., Ltd.", "Inc.", "U.S.", or "No.", picks the highest-overlap ETF pair,
// and ensures job progress percentages never decrease for the same running job_id
// while resetting when a reused job_id transitions from done/error back to running.

const ABBREVIATION_SUFFIX =
  /(?:^|[\s(,])(?:Co|Ltd|Inc|Corp|Plc|LLC|LP|NV|SA|AG|BV|US|USA|UK|EU|No|Nos|Dr|Mr|Mrs|Ms|St|Jr|Sr|vs|etc|approx|est|e\.g|i\.e|U\.S|U\.S\.A|U\.K|E\.U|L\.P|N\.V|S\.A|B\.V|[A-Z])\.$/i;

/**
 * Splits `text` into `[firstSentence, rest]` without splitting mid-sentence on
 * abbreviations like "Co., Ltd.", "Inc.", "U.S.", or "No.".
 */
export function splitFirstSentence(text: string): [string, string] {
  const trimmed = text.trim();
  if (!trimmed) return ["", ""];
  const re = /[.!?]\s+(?=[A-Z0-9"'(])/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(trimmed)) !== null) {
    const endIdx = match.index + 1;
    const prefix = trimmed.slice(0, endIdx);
    if (ABBREVIATION_SUFFIX.test(prefix)) {
      continue;
    }
    const rest = trimmed.slice(match.index + match[0].length).trim();
    return [prefix, rest];
  }
  return [trimmed, ""];
}

/**
 * FIX-16: Picks the ETF pair with the highest `weighted_overlap` rather than
 * taking `pairs[0]` in input order.
 */
export function pickMostOverlappingPair<T extends { weighted_overlap: number }>(
  pairs: readonly T[],
): T | null {
  let best: T | null = null;
  for (const pair of pairs) {
    if (!best || pair.weighted_overlap > best.weighted_overlap) {
      best = pair;
    }
  }
  return best;
}

const TERMINAL_STATUSES = new Set(["done", "error"]);
const ACTIVE_STATUSES = new Set(["queued", "running", "starting", "polling"]);

/**
 * FIX-18 + FIX-19: Ensures the displayed progress percentage (0..100) never decreases
 * for the same running `job_id`, while resetting when a reused `job_id` transitions
 * from a terminal state (`done`/`error`) back to an active run (`queued`/`running`).
 */
export function monotonicProgressPct(
  prevJobId: string | null,
  prevPct: number,
  nextJobId: string | null | undefined,
  rawPct: number,
  prevStatus?: string | null,
  nextStatus?: string | null,
): { jobId: string | null; pct: number; status: string | null } {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(rawPct) ? Math.round(rawPct) : 0));
  const jobId = nextJobId ?? null;
  const status = nextStatus ?? null;
  const restartedReusedJob =
    prevStatus != null &&
    TERMINAL_STATUSES.has(prevStatus) &&
    status != null &&
    ACTIVE_STATUSES.has(status);

  if (jobId && jobId === prevJobId && !restartedReusedJob) {
    return { jobId, pct: Math.max(prevPct, clamped), status };
  }
  return { jobId, pct: clamped, status };
}

/**
 * FIX-27: Determines whether a collapsible section should auto-expand when
 * its selection `expandKey` changes. Returns `shouldExpand: true` only when
 * `nextKey` is non-empty and differs from `prevKey`, so clicking "Show less"
 * while a node or edge remains selected does not re-open the section.
 */
export function shouldExpandOnKeyChange(
  prevKey: string | null | undefined,
  nextKey: string | null | undefined,
): { prevKey: string | null; shouldExpand: boolean } {
  const prev = prevKey ?? null;
  const next = nextKey ?? null;
  if (prev === next) {
    return { prevKey: prev, shouldExpand: false };
  }
  return { prevKey: next, shouldExpand: Boolean(next) };
}

const CORP_SUFFIX_RE =
  /,?\s+\b(?:Co\.,?\s*Ltd\.?|Corporation|Corp\.?|Incorporated|Inc\.?|Limited|Ltd\.?|PLC|Plc|N\.V\.?|S\.A\.?|AG|LLC|L\.P\.?)$/i;

const TRAILING_TAG_RE = /\s*\([a-z_]+\)\s*$/i;

function cleanEntityName(raw: string): string {
  return raw
    .trim()
    .replace(TRAILING_TAG_RE, "")
    .replace(CORP_SUFFIX_RE, "")
    .replace(CORP_SUFFIX_RE, "")
    .trim();
}

const PLAIN_OUTCOME_LABELS: Record<string, string> = {
  confirmed: "confirmed",
  new_evidence: "new link found",
  revised: "updated",
  rejected: "ruled out",
  unresolved: "still unclear",
};

/**
 * FIX-29 Part B: Formats a research finding into a single beginner-friendly plain line,
 * e.g. "Checked: Apple's reliance on Japan — confirmed".
 */
export function formatFindingOneLiner(
  subject: string,
  outcome: string,
  explanation?: string,
): string {
  const raw = subject.trim().replace(TRAILING_TAG_RE, "").trim();
  let plainSubject = raw;

  if (raw.includes("→")) {
    const [left, right] = raw.split("→", 2);
    const src = cleanEntityName(left ?? "");
    const tgt = cleanEntityName(right ?? "");
    if (src && tgt) {
      const possessive = src.endsWith("s") ? `${src}'` : `${src}'s`;
      plainSubject = `${possessive} reliance on ${tgt}`;
    }
  } else if (raw.includes(" — ")) {
    const [left, right] = raw.split(" — ", 2);
    const src = cleanEntityName(left ?? "");
    plainSubject = src && right ? `${src} (${right.trim()})` : raw;
  } else {
    plainSubject = cleanEntityName(raw) || raw;
  }

  const timedOut =
    typeof explanation === "string" &&
    /^not finished in time:/i.test(explanation.trim());
  const plainOutcome = timedOut
    ? "not finished in time"
    : (PLAIN_OUTCOME_LABELS[outcome] ?? outcome);

  return `Checked: ${plainSubject} — ${plainOutcome}`;
}
