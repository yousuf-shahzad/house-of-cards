// FIX-66: plain "what is the scan doing right now" text for a dependency job, so a scan sitting at 0%
// never looks frozen. Pure (type-only imports), so `node --test` loads it directly.
// Mounted by <ScanActivity> (scan-activity-view.tsx) under the progress bar on Full Dependencies,
// guide Step 4 and Simple Dependencies.

import type { CompanyRunStatus, CompanyStatus, DependencyJob } from "@/api/types";

/** Statuses that mean a company's report is finished with, successfully or not. */
const FINISHED: ReadonlySet<CompanyStatus> = new Set<CompanyStatus>([
  "done",
  "cached",
  "no_sec_filing",
  "unsupported_form",
  "sec_contact_missing",
  "missing_api_key",
  "error",
  "researching",
]);

export interface ScanActivity {
  /** What is happening now, e.g. "Reading Apple's annual report…". Null when the job is finished. */
  now: string | null;
  /** Progress through the companies, e.g. "Read 3 of 15 companies". Null before the list is known. */
  count: string | null;
}

/** "Apple Inc." -> "Apple", "NVIDIA Corporation" -> "NVIDIA". */
export function shortCompanyName(name: string): string {
  const cleaned = name
    .replace(/,?\s+\b(Inc\.?|Corp\.?|Corporation|Company|Co\.?|Ltd\.?|Limited|PLC|N\.V\.|S\.A\.|AG|SE|Holdings?)(?=[\s,]|$)/gi, "")
    .replace(/\s+(Class|Cl\.?)\s+[A-C]\b.*$/i, "")
    .trim();
  return cleaned || name.trim();
}

const possessive = (name: string) => (/s$/i.test(name) ? `${name}'` : `${name}'s`);

const biggestFirst = (a: CompanyRunStatus, b: CompanyRunStatus) =>
  b.exposure - a.exposure || a.company_name.localeCompare(b.company_name);

const andMore = (n: number) => (n > 0 ? ` and ${n} more` : "");

export function scanActivity(job: DependencyJob | null | undefined, starting = false): ScanActivity {
  // While starting, the store still holds the previous job (restartedJob keeps its companies), so ignore it.
  if (!job || starting) return { now: starting ? "Starting the scan…" : null, count: null };
  if (job.status === "done" || job.status === "error") {
    return { now: null, count: job.companies.length > 0 ? readCount(job.companies) : null };
  }

  const companies = job.companies;
  const count = companies.length > 0 ? readCount(companies) : null;

  if (job.phase === "synthesising") return { now: "Putting the results together…", count };

  if (job.phase === "researching") {
    const checking = companies.filter((c) => c.status === "researching").sort(biggestFirst);
    if (checking.length === 0) return { now: "Double-checking the findings…", count };
    const lead = shortCompanyName(checking[0].company_name);
    return { now: `Double-checking ${possessive(lead)} findings${andMore(checking.length - 1)}…`, count };
  }

  if (job.status === "queued" || job.phase === "queued" || companies.length === 0) {
    // A queued job's company statuses may still be the previous run's, so no count yet.
    return { now: "Getting ready to read the annual reports…", count: null };
  }

  const reading = companies.filter((c) => c.status === "extracting").sort(biggestFirst);
  const fetching = companies.filter((c) => c.status === "fetching").sort(biggestFirst);
  const active = reading.length + fetching.length;
  if (active === 0) {
    const waiting = companies.some((c) => c.status === "queued");
    return { now: waiting ? "Waiting for the next annual report…" : "Finishing the last reports…", count };
  }
  // Reading is further along than fetching, so it leads the line.
  const [verb, first] = reading.length > 0 ? ["Reading", reading[0]] : ["Fetching", fetching[0]];
  const name = possessive(shortCompanyName(first.company_name));
  return { now: `${verb} ${name} annual report${andMore(active - 1)}…`, count };
}

function readCount(companies: readonly CompanyRunStatus[]): string {
  const finished = companies.filter((c) => FINISHED.has(c.status)).length;
  const noun = companies.length === 1 ? "company" : "companies";
  return `Read ${finished} of ${companies.length} ${noun}`;
}

/** The bar should sweep (indeterminate) while a running scan still shows 0%, so it never looks frozen. */
export function scanBarIndeterminate(job: DependencyJob | null | undefined, pct: number, starting = false): boolean {
  const running = starting || job?.status === "queued" || job?.status === "running";
  return running && !(pct > 0);
}

/** "8 s", "1 min 05 s". */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  if (total < 60) return `${total} s`;
  const min = Math.floor(total / 60);
  const sec = String(total % 60).padStart(2, "0");
  return `${min} min ${sec} s`;
}
