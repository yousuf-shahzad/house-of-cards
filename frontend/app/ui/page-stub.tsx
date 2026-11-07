import { useAnalysis } from "@/app/analysis";

/** Placeholder shown until a page's owner replaces its stub. */
export function PageStub({ what }: { what: string }) {
  const { status } = useAnalysis();
  return (
    <section className="suite-card" aria-label="Page not built yet">
      <p className="text-body-medium text-text-primary">{what}: not built yet.</p>
      <p className="text-body-regular text-text-secondary">Analysis status: {status}.</p>
    </section>
  );
}
