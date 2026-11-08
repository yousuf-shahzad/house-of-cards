// FROZEN after W0-F: change only through the lead (see docs/hoc/PLAN.md).
// Each page owner edits only app/pages/<key>/, so pages never touch shared files.
import { lazy, type ComponentType, type LazyExoticComponent } from "react";
import {
  RiArrowLeftRightLine,
  RiBarChartHorizontalLine,
  RiCompass3Line,
  RiGridLine,
  RiLinksLine,
  RiPieChartLine,
  RiShieldCheckLine,
} from "@remixicon/react";
import { PageStub } from "./ui/page-stub";

export type PageKey =
  | "portfolio"
  | "exposures"
  | "overlap"
  | "dependencies"
  | "compare"
  | "risk"
  | "guide";

export type PageDefinition = {
  key: PageKey;
  label: string;
  href: `#/${PageKey}`;
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>;
  title: string;
  description: string;
  Component: LazyExoticComponent<ComponentType>;
  hiddenFromNav?: boolean;
};

const guideModules = import.meta.glob<{ default: ComponentType }>("./pages/guide/index.tsx");
const GuideFallback: ComponentType = () => <PageStub what="Guided view" />;
export const GuidePageComponent: LazyExoticComponent<ComponentType> = lazy(async () => {
  const loader = guideModules["./pages/guide/index.tsx"];
  return loader ? loader() : { default: GuideFallback };
});

export const pages: readonly PageDefinition[] = [
  {
    key: "portfolio",
    label: "Portfolio",
    href: "#/portfolio",
    icon: RiPieChartLine,
    title: "Your portfolio",
    description: "Enter your ETFs and how much of your money is in each.",
    Component: lazy(() => import("./pages/portfolio")),
  },
  {
    key: "exposures",
    label: "Exposures",
    href: "#/exposures",
    icon: RiBarChartHorizontalLine,
    title: "What you really own",
    description: "Your effective exposure to each company, across every ETF.",
    Component: lazy(() => import("./pages/exposures")),
  },
  {
    key: "overlap",
    label: "Overlap",
    href: "#/overlap",
    icon: RiGridLine,
    title: "ETF overlap",
    description: "How much your ETFs hold the same companies.",
    Component: lazy(() => import("./pages/overlap")),
  },
  {
    key: "dependencies",
    label: "Dependencies",
    href: "#/dependencies",
    icon: RiLinksLine,
    title: "What your companies depend on",
    description: "Suppliers, customers and facilities found in company filings, with the evidence.",
    Component: lazy(() => import("./pages/dependencies")),
  },
  {
    key: "compare",
    label: "Compare",
    href: "#/compare",
    icon: RiArrowLeftRightLine,
    title: "Compare a change",
    description: "Try a different allocation and see how your dependencies and concentration would change.",
    Component: lazy(() => import("./pages/compare")),
  },
  {
    key: "risk",
    label: "Risk & data",
    href: "#/risk",
    icon: RiShieldCheckLine,
    title: "Risk and data",
    description: "Concentration, sectors, data coverage and disclosure dates.",
    Component: lazy(() => import("./pages/risk")),
  },
  {
    key: "guide",
    label: "Guided view",
    href: "#/guide",
    icon: RiCompass3Line,
    title: "Guided portfolio check",
    description: "A five-step walkthrough of what you really own and where your hidden risks sit.",
    Component: GuidePageComponent,
    hiddenFromNav: true,
  },
];

export const defaultPage = pages[0];

/** Resolves "#/exposures" style hashes. Anything unknown goes to the default page. */
export function pageFromHash(hash: string): PageDefinition {
  const key = hash.replace(/^#\/?/, "").split(/[/?]/)[0];
  if (key === "network") return pages.find((page) => page.key === "exposures") ?? defaultPage;
  return pages.find((page) => page.key === key) ?? defaultPage;
}
