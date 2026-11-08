// FIX-66: the line under a dependency scan's progress bar: what it's doing now, how many companies are read,
// and how long it has been running. Put it right under the bar, and pass
// scanBarIndeterminate(job, pct, starting) as the bar's isIndeterminate so 0% still moves.
//
//   <ProgressBar value={pct} isIndeterminate={scanBarIndeterminate(job, pct, starting)} … />
//   <ScanActivity job={job} starting={starting} />

import { useEffect, useRef, useState } from "react";
import type { DependencyJob } from "@/api/types";
import { formatElapsed, scanActivity } from "@/app/ui/scan-activity";

export function ScanActivity({
  job,
  starting = false,
  className = "",
}: {
  job: DependencyJob | null | undefined;
  /** True between the click and the first job response. */
  starting?: boolean;
  className?: string;
}) {
  const running = starting || job?.status === "queued" || job?.status === "running";
  const elapsed = useElapsed(running, job?.job_id ?? null);
  if (!running) return null;
  const { now, count } = scanActivity(job, starting);
  const parts = [now, count, elapsed !== null ? formatElapsed(elapsed) : null].filter(Boolean);
  if (parts.length === 0) return null;
  return (
    <p
      role="status"
      aria-live="polite"
      className={`text-caption-1-regular text-text-secondary ${className}`}
      style={{ fontVariantNumeric: "tabular-nums" }}
    >
      {parts.join(" · ")}
    </p>
  );
}

/** Milliseconds since this run started, ticking once a second; null when not running. */
function useElapsed(running: boolean, jobId: string | null): number | null {
  const started = useRef<{ jobId: string | null; at: number } | null>(null);
  const [now, setNow] = useState(() => Date.now());

  if (!running) {
    started.current = null;
  } else if (!started.current || (jobId !== null && started.current.jobId !== null && started.current.jobId !== jobId)) {
    // A new run, or a different job than the one we were timing.
    started.current = { jobId, at: Date.now() };
  } else if (started.current.jobId === null && jobId !== null) {
    // The click came first; keep its start time once the job id arrives.
    started.current = { jobId, at: started.current.at };
  }

  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  return running && started.current ? Math.max(0, now - started.current.at) : null;
}
