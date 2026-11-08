"use client";
import { Component, Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import { RiMenuLine } from "@remixicon/react";
import { MOCK_MODE } from "@/api/client";
import { Button } from "@/components/base/buttons/button";
import { Chip } from "@/components/base/badges/chip";
import { Drawer, DrawerBody, DrawerHeader } from "@/components/base/drawer/drawer";
import { SegmentedControl, SegmentedControlItem } from "@/components/base/segmented-control/segmented-control";
import { useAnalysis } from "./analysis";
import { useExperience } from "./experience";
import { pageFromHash, pages } from "./registry";
import { SIMPLE_COPY, SIMPLE_PAGE_INFO } from "./pages/simple/copy";
import type { TabInfoGuide } from "./pages/guide/copy";

const SimplePage = lazy(() => import("./pages/simple"));
const DashboardSidebar = lazy(() =>
  import("@/components/application/dashboard/dashboard-sidebar").then((m) => ({ default: m.DashboardSidebar })),
);
const PageInfo = lazy(() =>
  Promise.all([import("./pages/guide"), import("./pages/guide/copy")]).then(([guide, copy]) => ({
    default: function PageInfo({ pageKey, simpleInfo }: { pageKey: string; simpleInfo?: TabInfoGuide }) {
      const info = simpleInfo ?? copy.PAGE_INFO_COPY[pageKey];
      return info ? <guide.TabInfoBanner info={info} /> : null;
    },
  })),
);
const PAGES_WITH_OWN_INFO = new Set(["exposures", "dependencies"]);
export const APP_NAME = "House of Cards";
export const APP_ICON = "/brand/hoc-icon.svg";
const navItems = pages.filter((page) => !page.hiddenFromNav).map(({ key, label, icon, href }) => ({ key, label, icon, href }));

class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    return <p role="alert" className="text-body-regular text-text-error-primary">This page hit an error. Your portfolio is safe: open another page or reload.</p>;
  }
}

export function Workspace() {
  const [hash, setHash] = useState(location.hash);
  const [mobile, setMobile] = useState(false);
  const [tips, setTips] = useState(true);
  const { analysis } = useAnalysis();
  const { isBeginner, setMode, openBeginnerGuide } = useExperience();
  const page = pageFromHash(hash);
  const simple = isBeginner && page.key !== "guide";
  const copy = SIMPLE_COPY[page.key];
  const Page = page.Component;
  const synthetic = MOCK_MODE || analysis?.etfs.some((etf) => etf.source === "fake") === true;

  useEffect(() => {
    const syncHash = () => {
      const rawKey = location.hash.replace(/^#\/?/, "").split(/[/?]/)[0];
      if (rawKey === "network") {
        window.location.hash = "#/exposures";
        setHash("#/exposures");
        setMobile(false);
        window.scrollTo({ top: 0 });
        return;
      }
      setHash(location.hash);
      setMobile(false);
      window.scrollTo({ top: 0 });
    };
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, []);
  useEffect(() => { document.title = page.label + " | " + APP_NAME; }, [page]);

  return (
    <div className="dashboard-shell suite-workspace">
      <div className="dashboard-sidebar-wrap">
        <Suspense fallback={<div className="sidebar-placeholder" />}>
          <DashboardSidebar workspaceName={APP_NAME} workspaceIcon={APP_ICON} selected={page.key} items={navItems} minimal className="telos-sidebar" />
        </Suspense>
      </div>
      <Drawer aria-label="Navigation" isOpen={mobile} onOpenChange={setMobile} placement="start" size="sm" className="mobile-workspace-drawer">
        <DrawerHeader title={APP_NAME} />
        <DrawerBody>
          <div onClickCapture={(event) => {
            if (event.target instanceof Element && event.target.closest('a[href^="#/"]')) setMobile(false);
          }}>
            <Suspense fallback={<p className="text-body-regular">Opening…</p>}>
              <DashboardSidebar workspaceName={APP_NAME} workspaceIcon={APP_ICON} selected={page.key} items={navItems} mobile fluid flat onClose={() => setMobile(false)} minimal className="telos-sidebar" />
            </Suspense>
          </div>
        </DrawerBody>
      </Drawer>
      <div className="dashboard-main">
        <header className="dashboard-topbar flex-wrap">
          <div className="workspace-breadcrumb">
            <Button variant="secondary" className="dash-menu" iconOnly leadingIcon={RiMenuLine} aria-label="Open navigation" onClick={() => setMobile(true)} />
            <span className="text-body-medium text-text-secondary">{APP_NAME}</span>
            <span className="text-text-tertiary" aria-hidden>/</span>
            <span className="text-body-medium text-text-primary">{page.label}</span>
            {synthetic && <Chip variant="caption" color="rose" role="status">SYNTHETIC data: not real holdings</Chip>}
          </div>
          <div className="ms-auto flex shrink-0 items-center gap-3">
            {simple && <Button variant="ghost" size="small" aria-pressed={tips} onClick={() => setTips((value) => !value)}>{tips ? "Hide tips" : "Show tips"}</Button>}
            <SegmentedControl aria-label="View" selectedKeys={[isBeginner ? "beginner" : "expert"]} onSelectionChange={(keys) => {
              const next = [...keys][0];
              if (next === "beginner" || next === "expert") setMode(next);
            }}>
              <SegmentedControlItem id="beginner">Simple</SegmentedControlItem>
              <SegmentedControlItem id="expert">Full</SegmentedControlItem>
            </SegmentedControl>
          </div>
        </header>
        <main id="main" tabIndex={-1} className="dashboard-body">
          {page.key !== "guide" && (
            <div className="dashboard-heading">
              <div>
                <h1 className="text-display-4-medium">{simple ? copy?.title : page.title}</h1>
                <p className="text-body-regular text-text-secondary">{simple ? copy?.description : page.description}</p>
                {(simple || !PAGES_WITH_OWN_INFO.has(page.key)) && (
                  <div className="mt-3"><Suspense fallback={null}><PageInfo key={page.key + "-" + simple} pageKey={page.key} simpleInfo={simple ? SIMPLE_PAGE_INFO[page.key] : undefined} /></Suspense></div>
                )}
              </div>
            </div>
          )}
          {simple && tips && copy && (
            <aside aria-label="Page tip" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-separator-border bg-background-secondary-default p-4">
              <div className="flex max-w-2xl flex-col gap-1">
                <p className="text-body-medium text-text-primary">{copy.tip}</p>
                <p className="text-caption-1-regular text-text-secondary">Use any page in the sidebar. Choose Full above for more detail.</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="ghost" size="small" onClick={() => openBeginnerGuide()}>Open the five-step guide</Button>
                <Button variant="ghost" size="small" onClick={() => setTips(false)}>Dismiss tips</Button>
              </div>
            </aside>
          )}
          <PageBoundary key={page.key + "-" + simple}>
            <Suspense fallback={<p className="text-body-regular text-text-secondary">Loading…</p>}>
              {simple ? <SimplePage pageKey={page.key} /> : <Page />}
            </Suspense>
          </PageBoundary>
          {analysis && analysis.attributions.length > 0 && (
            <footer aria-label="Data attributions" className="mt-6 border-t border-separator-border pt-4 text-caption-1-regular text-text-tertiary">
              <ul className="flex flex-col gap-1.5">
                {analysis.attributions.map((attr, idx) => (
                  <li key={attr.source + "-" + idx} className="flex flex-wrap items-center gap-2">
                    <span>{attr.text}</span>
                    {attr.licence && <Chip variant="caption" color="neutral">{attr.licence}</Chip>}
                    {attr.url && <a href={attr.url} target="_blank" rel="noreferrer" className="underline hover:text-text-secondary">Source</a>}
                  </li>
                ))}
              </ul>
            </footer>
          )}
        </main>
      </div>
    </div>
  );
}
