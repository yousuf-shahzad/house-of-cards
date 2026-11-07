"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { Focusable } from "react-aria-components";
import { EtfChip } from "@/app/ui/etf-chip";
import { etfVisual } from "@/app/ui/etf-color";
import { Pct, formatPct } from "@/app/ui/pct";
import { Tooltip, TooltipTrigger } from "@/components/base/tooltip/tooltip";
import { cx } from "@/utils/cx";

export interface HeatmapMatrixProps {
  /** Ordered ETF tickers for rows and columns. */
  etfs: readonly string[];
  /** Symmetric NxN matrix of weights (fractions of 1). Diagonal = ETF holdings_weight; off-diagonal = pair overlap. */
  matrix: readonly (readonly number[])[];
  /** Optional lookup returning an ETF's index in `AnalysisResponse.etfs` so `etfVisual(index)` stays consistent across pages. */
  getEtfIndex?: (ticker: string, fallbackIndex: number) => number;
  /** Currently selected pair [etfA, etfB] (order-insensitive). */
  selectedPair?: readonly [string, string] | null;
  /** Invoked when the user selects an off-diagonal pair cell. */
  onSelectPair?: (etfA: string, etfB: string) => void;
  /** Optional subtitle rendered inside each cell (e.g. shared company count or "Covered NAV"). */
  getCellSubtitle?: (rowTicker: string, colTicker: string, value: number, isDiagonal: boolean) => ReactNode;
  /** Optional accessible title/tooltip per cell. */
  getCellTitle?: (rowTicker: string, colTicker: string, value: number, isDiagonal: boolean) => string | undefined;
  /** Optional metadata rendered under each row's ticker chip. */
  renderRowMeta?: (ticker: string, index: number) => ReactNode;
  /** Label shown on diagonal cells when `getCellSubtitle` is not provided. */
  diagonalCaption?: string;
  /** Label shown on off-diagonal cells when `getCellSubtitle` is not provided. */
  pairCaption?: string;
  /** Accessible label for the heatmap grid. */
  ariaLabel?: string;
  className?: string;
}

const LEGEND_STOPS = [0, 0.15, 0.35, 0.6] as const;

function heatBackground(weight: number, isDiagonal: boolean): string | undefined {
  if (isDiagonal) return undefined;
  const clamped = Number.isFinite(weight) ? Math.max(0, Math.min(1, weight)) : 0;
  if (clamped <= 0) return undefined;
  // Smooth semantic mix between secondary surface and accent-500 (14%..50%) so text-primary stays high-contrast in both light and dark modes.
  const pct = Math.round(14 + Math.pow(clamped, 0.75) * 36);
  return `color-mix(in srgb, var(--color-accent-500) ${pct}%, var(--color-background-secondary-default))`;
}

function isSamePair(
  pair: readonly [string, string] | null | undefined,
  a: string,
  b: string,
): boolean {
  if (!pair) return false;
  const [x, y] = pair;
  return (x === a && y === b) || (x === b && y === a);
}

/** Small visual swatch using `etfVisual(index)` (colour + optional dash pattern for ETFs 6..10). */
export function EtfColorSwatch({
  index,
  className,
}: {
  index: number;
  className?: string;
}) {
  const { color, dash } = etfVisual(index);
  return (
    <span
      aria-hidden
      className={cx("inline-block size-2.5 shrink-0 rounded-full", className)}
      style={
        dash
          ? {
              backgroundColor: color,
              boxShadow: "inset 0 0 0 1.5px var(--color-background-primary-default)",
              border: `1.5px dashed ${color}`,
            }
          : { backgroundColor: color }
      }
    />
  );
}

export function HeatmapMatrix({
  etfs,
  matrix,
  getEtfIndex,
  selectedPair,
  onSelectPair,
  getCellSubtitle,
  getCellTitle,
  renderRowMeta,
  diagonalCaption = "Covered NAV",
  pairCaption = "Overlap",
  ariaLabel = "ETF pairwise overlap heatmap",
  className,
}: HeatmapMatrixProps) {
  const cellRefs = useRef<Map<string, HTMLElement>>(new Map());
  const n = etfs.length;

  function resolveEtfIndex(ticker: string, fallbackIndex: number): number {
    return getEtfIndex ? getEtfIndex(ticker, fallbackIndex) : fallbackIndex;
  }

  function focusCell(r: number, c: number) {
    const row = (r + n) % n;
    const col = (c + n) % n;
    cellRefs.current.get(`${row}:${col}`)?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>, rowIdx: number, colIdx: number) {
    switch (event.key) {
      case "ArrowRight":
        event.preventDefault();
        focusCell(rowIdx, colIdx + 1);
        break;
      case "ArrowLeft":
        event.preventDefault();
        focusCell(rowIdx, colIdx - 1);
        break;
      case "ArrowDown":
        event.preventDefault();
        focusCell(rowIdx + 1, colIdx);
        break;
      case "ArrowUp":
        event.preventDefault();
        focusCell(rowIdx - 1, colIdx);
        break;
      case "Home":
        event.preventDefault();
        focusCell(rowIdx, 0);
        break;
      case "End":
        event.preventDefault();
        focusCell(rowIdx, n - 1);
        break;
    }
  }

  if (n === 0) {
    return null;
  }

  return (
    <div className={cx("flex flex-col gap-4", className)}>
      <div className="w-full overflow-x-auto pb-1">
        <div
          role="grid"
          aria-label={ariaLabel}
          aria-rowcount={n + 1}
          aria-colcount={n + 1}
          className="grid items-stretch gap-2"
          style={{
            gridTemplateColumns: `minmax(9rem, auto) repeat(${n}, minmax(6.75rem, 1fr))`,
            minWidth: `${Math.max(20, (n + 1) * 7.25)}rem`,
          }}
        >
          {/* Header row */}
          <div role="row" aria-rowindex={1} className="contents">
            <div
              role="columnheader"
              aria-colindex={1}
              className="flex items-end pb-1.5 pe-2 text-caption-1-medium text-text-tertiary"
            >
              ETF × ETF
            </div>
            {etfs.map((colTicker, colIdx) => {
              const visualIdx = resolveEtfIndex(colTicker, colIdx);
              const { color, dash } = etfVisual(visualIdx);
              return (
                <div
                  key={`col-${colTicker}`}
                  role="columnheader"
                  aria-colindex={colIdx + 2}
                  className="flex flex-col items-center justify-end gap-1.5 rounded-xl bg-background-secondary-default px-2 py-2 text-center"
                  style={{
                    borderBottom: `3px ${dash ? "dashed" : "solid"} ${color}`,
                  }}
                >
                  <div className="flex items-center gap-1.5">
                    <EtfColorSwatch index={visualIdx} />
                    <EtfChip ticker={colTicker} />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Matrix rows */}
          {etfs.map((rowTicker, rowIdx) => {
            const visualIdx = resolveEtfIndex(rowTicker, rowIdx);
            const { color, dash } = etfVisual(visualIdx);
            return (
              <div
                key={`row-${rowTicker}`}
                role="row"
                aria-rowindex={rowIdx + 2}
                className="contents"
              >
                <div
                  role="rowheader"
                  aria-colindex={1}
                  className="flex flex-col items-start justify-center gap-1 rounded-xl bg-background-secondary-default px-3 py-2"
                  style={{
                    borderInlineStart: `3px ${dash ? "dashed" : "solid"} ${color}`,
                  }}
                >
                  <div className="flex items-center gap-1.5">
                    <EtfColorSwatch index={visualIdx} />
                    <EtfChip ticker={rowTicker} />
                  </div>
                  {renderRowMeta ? (
                    <div className="text-caption-1-regular text-text-secondary">
                      {renderRowMeta(rowTicker, rowIdx)}
                    </div>
                  ) : null}
                </div>

                {etfs.map((colTicker, colIdx) => {
                  const isDiagonal = rowIdx === colIdx;
                  const value = matrix[rowIdx]?.[colIdx] ?? 0;
                  const selected =
                    !isDiagonal && isSamePair(selectedPair, rowTicker, colTicker);
                  const subtitle = getCellSubtitle
                    ? getCellSubtitle(rowTicker, colTicker, value, isDiagonal)
                    : isDiagonal
                      ? diagonalCaption
                      : pairCaption;
                  const title = getCellTitle
                    ? getCellTitle(rowTicker, colTicker, value, isDiagonal)
                    : isDiagonal
                      ? `${rowTicker} Covered NAV (${formatPct(value)}): the share of this ETF we could look through, excluding cash and derivatives.`
                      : `${rowTicker} × ${colTicker} overlap: ${formatPct(value)}`;
                  const bg = heatBackground(value, isDiagonal);
                  const cellKey = `${rowIdx}:${colIdx}`;

                  if (isDiagonal) {
                    return (
                      <TooltipTrigger key={cellKey} delay={150}>
                        <Focusable>
                          <div
                            ref={(node) => {
                              if (node) cellRefs.current.set(cellKey, node);
                              else cellRefs.current.delete(cellKey);
                            }}
                            role="gridcell"
                            aria-colindex={colIdx + 2}
                            aria-readonly="true"
                            tabIndex={0}
                            title={title}
                            aria-label={title}
                            onKeyDown={(e) => handleKeyDown(e, rowIdx, colIdx)}
                            className={cx(
                              "flex min-h-[4.75rem] cursor-help flex-col items-center justify-center gap-1 rounded-2xl p-2.5 text-center",
                              "border border-dashed border-border-button-default bg-background-secondary-default",
                              "outline-none focus-visible:ring-2 focus-visible:ring-border-focus-ring",
                            )}
                          >
                            <Pct
                              value={value}
                              className="text-title-3-semibold text-text-secondary"
                            />
                            <span className="text-caption-1-regular text-text-tertiary underline decoration-dotted underline-offset-2">
                              {subtitle}
                            </span>
                          </div>
                        </Focusable>
                        <Tooltip size="sm">{title}</Tooltip>
                      </TooltipTrigger>
                    );
                  }

                  return (
                    <TooltipTrigger key={cellKey} delay={150}>
                      <Focusable>
                        <button
                          ref={(node) => {
                            if (node) cellRefs.current.set(cellKey, node);
                            else cellRefs.current.delete(cellKey);
                          }}
                          type="button"
                          role="gridcell"
                          aria-colindex={colIdx + 2}
                          aria-selected={selected}
                          aria-pressed={selected}
                          aria-label={title}
                          title={title}
                          onClick={() => onSelectPair?.(rowTicker, colTicker)}
                          onKeyDown={(e) => handleKeyDown(e, rowIdx, colIdx)}
                          style={bg ? { backgroundColor: bg } : undefined}
                          className={cx(
                            "flex min-h-[4.75rem] cursor-pointer flex-col items-center justify-center gap-1 rounded-2xl p-2.5 text-center",
                            "border transition-[border-color,box-shadow,transform] duration-150 ease",
                            "outline-none focus-visible:ring-2 focus-visible:ring-border-focus-ring",
                            !bg && "bg-background-secondary-default hover:bg-background-secondary-hover",
                            selected
                              ? "border-border-focus-ring ring-2 ring-border-focus-ring"
                              : "border-border-button-default hover:border-border-button-hover",
                          )}
                        >
                          <Pct
                            value={value}
                            className="text-title-3-semibold text-text-primary"
                          />
                          <span className="text-caption-1-medium text-text-secondary">
                            {subtitle}
                          </span>
                        </button>
                      </Focusable>
                      <Tooltip size="sm">{title}</Tooltip>
                    </TooltipTrigger>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>

      {/* Heat scale & diagonal key */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-1 text-caption-1-regular text-text-tertiary">
        <div className="flex items-center gap-2">
          <span>Lower overlap</span>
          {LEGEND_STOPS.map((stop) => {
            const bg = heatBackground(stop, false);
            return (
              <span
                key={stop}
                aria-hidden
                style={bg ? { backgroundColor: bg } : undefined}
                className={cx(
                  "inline-block size-4 rounded-sm border border-separator-border",
                  !bg && "bg-background-secondary-default",
                )}
              />
            );
          })}
          <span>Higher overlap</span>
        </div>
        <span>
          Diagonal cells (<span className="text-text-secondary">dashed</span>) show each ETF’s covered holdings weight; use arrow keys or click any pair cell to inspect.
        </span>
      </div>
    </div>
  );
}
