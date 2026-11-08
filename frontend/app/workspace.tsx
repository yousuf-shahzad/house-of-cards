"use client";
import { Component, Suspense, lazy, useEffect, useRef, useState, type ReactNode } from "react";
import { RiCompass3Line, RiMenuLine } from "@remixicon/react";
import { MOCK_MODE } from "@/api/client";
import { Button } from "@/components/base/buttons/button";
import { Chip } from "@/components/base/badges/chip";
import { Drawer, DrawerBody, DrawerHeader } from "@/components/base/drawer/drawer";
import { Switch } from "@/components/base/switch/switch";
import { useAnalysis } from "./analysis";
import { useExperience } from "./experience";
import { GuidePageComponent, pageFromHash, pages } from "./registry";

const DashboardSidebar = lazy(() =>
  import("@/components/application/dashboard/dashboard-sidebar").then((m) => ({
    default: m.DashboardSidebar,
  })),
);

/** FIX-28: "What's here & why" for the Full-view pages that don't render their own. Lazy, so the guide bundle
 * (where the banner and its copy live) stays out of the main chunk. */
const PageInfo = lazy(() =>
  Promise.all([import("./pages/guide"), import("./pages/guide/copy")]).then(([guide, copy]) => ({
    default: function PageInfo({ pageKey }: { pageKey: string }) {
      const info = copy.PAGE_INFO_COPY[pageKey];
      return info ? <guide.TabInfoBanner info={info} /> : null;
    },
  })),
);
/** Pages that already show their own banner (with page-specific placement). */
const PAGES_WITH_OWN_INFO = new Set(["exposures", "dependencies"]);

export const APP_NAME = "House of Cards";

const navItems = pages
  .filter((page) => !page.hiddenFromNav && page.key !== "guide")
  .map(({ key, label, icon, href }) => ({ key, label, icon, href }));

/** Keeps one page's crash from taking down the rest of the app. */
class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <p role="alert" className="text-body-regular text-text-error-primary">
        This page hit an error. Your portfolio is safe: open another page or reload.
      </p>
    );
  }
}

export function Workspace() {
  const [hash, setHash] = useState(location.hash);
  const [mobile, setMobile] = useState(false);
  const { analysis } = useAnalysis();
  const { isBeginner, setMode, step, setStep, totalSteps } = useExperience();
  const [hasVisitedBeginner, setHasVisitedBeginner] = useState(false);
  const guideWrapperRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (isBeginner) {
      setHasVisitedBeginner(true);
    }
  }, [isBeginner]);

  const synthetic = MOCK_MODE || analysis?.etfs.some((etf) => etf.source === "fake") === true;

  useEffect(() => {
    const onHash = () => {
      setHash(location.hash);
      setMobile(false);
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  // Keep the top-bar "Step N of 5" indicator in sync even if the Guide page manages its own local step state.
  useEffect(() => {
    const container = guideWrapperRef.current;
    if (!container || !isBeginner) return;

    const syncStepFromDom = () => {
      const explicitEl = container.querySelector<HTMLElement>("[data-guide-step]");
      if (explicitEl?.dataset.guideStep) {
        const parsed = Number(explicitEl.dataset.guideStep);
        if (Number.isFinite(parsed) && parsed >= 1 && parsed <= totalSteps) {
          setStep(parsed);
          return;
        }
      }
      const progressBar = container.querySelector<HTMLElement>('[role="progressbar"]');
      if (progressBar) {
        const valueText = progressBar.getAttribute("aria-valuetext") ?? "";
        const textMatch = valueText.match(/Step\s+(\d+)\s+of\s+5/i);
        if (textMatch) {
          setStep(Number(textMatch[1]));
          return;
        }
        const nowAttr = progressBar.getAttribute("aria-valuenow");
        const maxAttr = progressBar.getAttribute("aria-valuemax");
        if (nowAttr != null) {
          const now = Number(nowAttr);
          const max = maxAttr != null ? Number(maxAttr) : 100;
          if (Number.isFinite(now) && Number.isFinite(max) && max > 0) {
            if (max === totalSteps && now >= 1 && now <= totalSteps) {
              setStep(Math.round(now));
              return;
            }
            const derived = Math.round((now / max) * totalSteps);
            if (derived >= 1 && derived <= totalSteps) {
              setStep(derived);
              return;
            }
          }
        }
      }
      const match = container.textContent?.match(/Step\s+(\d+)\s+of\s+5/i);
      if (match) {
        setStep(Number(match[1]));
      }
    };

    syncStepFromDom();
    const observer = new MutationObserver(syncStepFromDom);
    observer.observe(container, {
      subtree: true,
      childList: true,
      attributes: true,
      characterData: true,
    });
    return () => observer.disconnect();
  }, [isBeginner, setStep, totalSteps]);

  const resolvedPage = pageFromHash(hash);
  const page = isBeginner
    ? (pages.find((p) => p.key === "guide") ?? resolvedPage)
    : resolvedPage.key === "guide"
      ? pages[0]
      : resolvedPage;

  useEffect(() => {
    document.title = `${page.label} | ${APP_NAME}`;
  }, [page]);

  const Page = page.Component;

  const modeSwitch = (
    <div className="ms-auto flex shrink-0 items-center gap-2">
      <Switch
        size="sm"
        aria-label="Simple view / Full view"
        isSelected={!isBeginner}
        onChange={(fullView) => setMode(fullView ? "expert" : "beginner")}
      >
        <span className="text-caption-1-medium text-text-secondary">
          Simple view / Full view
        </span>
      </Switch>
    </div>
  );

  return (
    <div className="dashboard-shell suite-workspace">
      {!isBeginner && (
        <>
          <div className="dashboard-sidebar-wrap">
            <Suspense fallback={<div className="sidebar-placeholder" />}>
              <DashboardSidebar
                workspaceName={APP_NAME}
                selected={page.key}
                items={navItems}
                minimal
                className="telos-sidebar"
              />
            </Suspense>
          </div>
          <Drawer
            aria-label="Navigation"
            isOpen={mobile}
            onOpenChange={setMobile}
            placement="start"
            size="sm"
            className="mobile-workspace-drawer"
          >
            <DrawerHeader title={APP_NAME} />
            <DrawerBody>
              <Suspense fallback={<p className="text-body-regular">Opening…</p>}>
                <DashboardSidebar
                  workspaceName={APP_NAME}
                  selected={page.key}
                  items={navItems}
                  mobile
                  fluid
                  flat
                  onClose={() => setMobile(false)}
                  minimal
                  className="telos-sidebar"
                />
              </Suspense>
            </DrawerBody>
          </Drawer>
        </>
      )}
      <div className="dashboard-main">
        <header className="dashboard-topbar flex-wrap">
          {isBeginner ? (
            <div className="workspace-breadcrumb flex min-w-0 flex-wrap items-center gap-2">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-accent-500/10 text-accent-500">
                <RiCompass3Line className="size-4" aria-hidden />
              </span>
              <span className="text-body-medium text-text-primary">{APP_NAME}</span>
              <span className="text-text-tertiary" aria-hidden>
                /
              </span>
              <span
                className="text-body-medium text-text-secondary tabular-nums"
                data-testid="topbar-step-label"
              >
                Step {step} of {totalSteps}
              </span>
            </div>
          ) : (
            <div className="workspace-breadcrumb">
              <Button
                variant="secondary"
                className="dash-menu"
                iconOnly
                leadingIcon={RiMenuLine}
                aria-label="Open navigation"
                onClick={() => setMobile(true)}
              />
              <span className="text-body-medium text-text-secondary">{APP_NAME}</span>
              <span className="text-text-tertiary">/</span>
              <span className="text-body-medium text-text-primary">{page.label}</span>
              {synthetic && (
                <Chip variant="caption" color="rose" role="status">
                  SYNTHETIC data: not real holdings
                </Chip>
              )}
            </div>
          )}
          {modeSwitch}
        </header>
        <main id="main" tabIndex={-1} className="dashboard-body">
          {(isBeginner || hasVisitedBeginner) && (
            <div
              ref={guideWrapperRef}
              hidden={!isBeginner}
              aria-hidden={!isBeginner || undefined}
              className={
                isBeginner ? "mx-auto flex w-full max-w-[720px] flex-col gap-6" : "hidden"
              }
            >
              <PageBoundary key="guide">
                <Suspense
                  fallback={<p className="text-body-regular text-text-secondary">Loading…</p>}
                >
                  <GuidePageComponent />
                </Suspense>
              </PageBoundary>
            </div>
          )}
          {!isBeginner && (
            <>
              <div className="dashboard-heading">
                <div>
                  <h1 className="text-display-4-medium">{page.title}</h1>
                  <p className="text-body-regular text-text-secondary">{page.description}</p>
                  {!PAGES_WITH_OWN_INFO.has(page.key) && (
                    <div className="mt-3">
                      <Suspense fallback={null}>
                        <PageInfo key={page.key} pageKey={page.key} />
                      </Suspense>
                    </div>
                  )}
                </div>
              </div>
              <PageBoundary key={page.key}>
                <Suspense
                  fallback={<p className="text-body-regular text-text-secondary">Loading…</p>}
                >
                  <Page />
                </Suspense>
              </PageBoundary>
              {analysis && analysis.attributions.length > 0 && (
                <footer
                  aria-label="Data attributions"
                  className="mt-6 border-t border-separator-border pt-4 text-caption-1-regular text-text-tertiary"
                >
                  <ul className="flex flex-col gap-1.5">
                    {analysis.attributions.map((attr, idx) => (
                      <li
                        key={`${attr.source}-${idx}`}
                        className="flex flex-wrap items-center gap-2"
                      >
                        <span>{attr.text}</span>
                        {attr.licence && (
                          <Chip variant="caption" color="neutral">
                            {attr.licence}
                          </Chip>
                        )}
                        {attr.url && (
                          <a
                            href={attr.url}
                            target="_blank"
                            rel="noreferrer"
                            className="underline hover:text-text-secondary"
                          >
                            Source
                          </a>
                        )}
                      </li>
                    ))}
                  </ul>
                </footer>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
