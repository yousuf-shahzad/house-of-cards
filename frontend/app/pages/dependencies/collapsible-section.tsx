"use client";
// Page-local collapsible section for the Dependencies page (FIX-23).
// - Collapsed by default with a ~280px preview and a theme-token bottom fade (light & dark).
// - Toggle button exposes `aria-expanded` and `aria-controls`.
// - Tabbing/focusing into the hidden/preview body automatically unfolds the section.
// - Remembers each section's state per viewer in `localStorage`, wrapped in `try/catch`.
// - Supports `expandKey` so selecting a new edge or node elsewhere (e.g. from an insight card)
//   expands the Graph section on selection change without persisting forced opens or blocking "Show less".

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type ReactNode,
} from "react";
import { RiArrowDownSLine, RiArrowUpSLine } from "@remixicon/react";

import { Button } from "@/components/base/buttons/button";
import { shouldExpandOnKeyChange } from "../guide/sentence";

export function readStoredCollapsibleState(
  storageKey: string,
  defaultExpanded = false,
): boolean {
  try {
    if (typeof window === "undefined" || !window.localStorage) {
      return defaultExpanded;
    }
    const raw = window.localStorage.getItem(storageKey);
    if (raw === "1" || raw === "true") return true;
    if (raw === "0" || raw === "false") return false;
  } catch {
    // Ignore storage quota or privacy-mode errors.
  }
  return defaultExpanded;
}

export function writeStoredCollapsibleState(
  storageKey: string,
  expanded: boolean,
): void {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      window.localStorage.setItem(storageKey, expanded ? "1" : "0");
    }
  } catch {
    // Ignore storage quota or privacy-mode errors.
  }
}

export type CollapsibleSectionProps = {
  /** Key in localStorage used to persist this section's expanded state per viewer. */
  storageKey: string;
  /** Accessible region label for `<section aria-label={...}>`. */
  ariaLabel: string;
  /** Leading header icon. */
  icon?: ReactNode;
  /** Section title. */
  title: string;
  /** Inline chips or count badges rendered next to the title. */
  badges?: ReactNode;
  /** One-line summary or count shown in the header. */
  summary?: ReactNode;
  /** Right-aligned header actions or metadata (e.g. "Investigate gaps" button). */
  headerActions?: ReactNode;
  /** Optional status/alert block shown directly under the header before the collapsible preview. */
  subHeader?: ReactNode;
  /** Preview height in pixels when collapsed (default: 280). */
  previewHeight?: number;
  /** Collapsed by default (`false`). */
  defaultExpanded?: boolean;
  /** When this key changes to a non-null value (e.g. `selectedEdgeId ?? selectedNodeId`), unfolds the section without persisting or blocking subsequent "Show less" clicks. */
  expandKey?: string | null;
  children: ReactNode;
};

export function CollapsibleSection({
  storageKey,
  ariaLabel,
  icon,
  title,
  badges,
  summary,
  headerActions,
  subHeader,
  previewHeight = 280,
  defaultExpanded = false,
  expandKey = null,
  children,
}: CollapsibleSectionProps) {
  const reactId = useId();
  const contentId = `dep-collapsible-${storageKey.replace(/[^a-zA-Z0-9_-]/g, "-")}-${reactId.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const contentRef = useRef<HTMLDivElement | null>(null);
  const pointerDownRef = useRef(false);
  const prevExpandKeyRef = useRef<string | null>(expandKey ?? null);

  const [expanded, setExpanded] = useState<boolean>(() =>
    readStoredCollapsibleState(storageKey, defaultExpanded),
  );

  const updateExpanded = useCallback(
    (next: boolean) => {
      setExpanded(next);
      writeStoredCollapsibleState(storageKey, next);
    },
    [storageKey],
  );

  useEffect(() => {
    const { prevKey, shouldExpand } = shouldExpandOnKeyChange(
      prevExpandKeyRef.current,
      expandKey,
    );
    prevExpandKeyRef.current = prevKey;
    if (shouldExpand) {
      setExpanded(true);
    }
  }, [expandKey]);

  const handleFocusCapture = useCallback(
    (ev: FocusEvent<HTMLDivElement>) => {
      if (expanded) return;
      if (pointerDownRef.current) {
        const container = contentRef.current;
        const target = ev.target;
        if (container && target instanceof HTMLElement) {
          const cRect = container.getBoundingClientRect();
          const tRect = target.getBoundingClientRect();
          if (tRect.bottom <= cRect.bottom - 16) {
            return;
          }
        }
      }
      updateExpanded(true);
    },
    [expanded, updateExpanded],
  );

  return (
    <section
      aria-label={ariaLabel}
      className="flex flex-col gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            {icon}
            <h3 className="text-headline-small text-text-primary">{title}</h3>
            {badges}
          </div>
          {summary && (
            <div className="text-body-2-regular text-text-secondary">{summary}</div>
          )}
        </div>
        {headerActions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {headerActions}
          </div>
        )}
      </div>

      {subHeader}

      <div
        id={contentId}
        ref={contentRef}
        onPointerDownCapture={() => {
          pointerDownRef.current = true;
          if (typeof window !== "undefined") {
            window.setTimeout(() => {
              pointerDownRef.current = false;
            }, 0);
          }
        }}
        onFocusCapture={handleFocusCapture}
        style={expanded ? undefined : { maxHeight: `${previewHeight}px` }}
        className={
          expanded
            ? "flex flex-col gap-4"
            : "relative flex flex-col gap-4 overflow-hidden"
        }
      >
        {children}
        {!expanded && (
          <div
            aria-hidden="true"
            data-testid="collapsible-fade"
            className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-linear-to-t from-background-secondary-default via-background-secondary-default/85 to-transparent"
            style={{
              background:
                "linear-gradient(to top, var(--color-background-secondary-default) 12%, color-mix(in srgb, var(--color-background-secondary-default) 82%, transparent) 58%, transparent 100%)",
            }}
          />
        )}
      </div>

      <div className="flex items-center justify-start pt-1">
        <Button
          variant="secondary"
          size="xs"
          aria-expanded={expanded}
          aria-controls={contentId}
          leadingIcon={expanded ? RiArrowUpSLine : RiArrowDownSLine}
          onClick={() => updateExpanded(!expanded)}
        >
          {expanded ? "Show less" : "Show all"}
        </Button>
      </div>
    </section>
  );
}
