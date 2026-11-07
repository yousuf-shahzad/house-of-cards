"use client";
import { Component, Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import { RiMenuLine } from "@remixicon/react";
import { MOCK_MODE } from "@/api/client";
import { Button } from "@/components/base/buttons/button";
import { Chip } from "@/components/base/badges/chip";
import { Drawer, DrawerBody, DrawerHeader } from "@/components/base/drawer/drawer";
import { useAnalysis } from "./analysis";
import { pageFromHash, pages } from "./registry";

const DashboardSidebar = lazy(() =>
  import("@/components/application/dashboard/dashboard-sidebar").then((m) => ({
    default: m.DashboardSidebar,
  })),
);

export const APP_NAME = "House of Cards";

const navItems = pages.map(({ key, label, icon, href }) => ({ key, label, icon, href }));

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
  const page = pageFromHash(hash);
  useEffect(() => {
    document.title = `${page.label} | ${APP_NAME}`;
  }, [page]);
  const Page = page.Component;
  return (
    <div className="dashboard-shell suite-workspace">
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
      <div className="dashboard-main">
        <header className="dashboard-topbar">
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
        </header>
        <main id="main" tabIndex={-1} className="dashboard-body">
          <div className="dashboard-heading">
            <div>
              <h1 className="text-display-4-medium">{page.title}</h1>
              <p className="text-body-regular text-text-secondary">{page.description}</p>
            </div>
          </div>
          <PageBoundary key={page.key}>
            <Suspense fallback={<p className="text-body-regular text-text-secondary">Loading…</p>}>
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
                  <li key={`${attr.source}-${idx}`} className="flex flex-wrap items-center gap-2">
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
        </main>
      </div>
    </div>
  );
}
