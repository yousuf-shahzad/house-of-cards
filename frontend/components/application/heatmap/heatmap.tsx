"use client";

import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { EtfChip } from "@/app/ui/etf-chip";
import { Pct, formatPct } from "@/app/ui/pct";
import { cx } from "@/utils/cx";

export interface HeatmapMatrixProps {
  /** Ordered ETF tickers for rows and columns. */
  etfs: readonly string[];
  /** Symmetric NxN matrix of weights (fractions of 1). Diagonal = ETF holdings_weight; off-diagonal = pair overlap. */
  matrix: readonly (readonly number[])[];
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
  // Smooth semantic mix between secondary surface and accent-500 (14%..58%) so text-primary stays high-contrast in light & dark mode.
  const pct = Math.round(14 + Math.pow(clamped, 0.75) * 44);
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

export function HeatmapMatrix({
  etfs,
  matrix,
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
          className="grid items-stretch gap-2"
          style={{
            gridTemplateColumns: `minmax(8.5rem, auto) repeat(${n}, minmax(6.75rem, 1fr))`,
            minWidth: `${Math.max(20, (n + 1) * 7.25)}rem`,
          }}
        >
          {/* Top-start corner cell */}
          <div role="row" className="contents">
            <div
              role="columnheader"
              className="flex items-end pb-1 pe-2 text-caption-1-medium text-text-tertiary"
            >
              ETF × ETF
            </div>
            {etfs.map((colTicker) => (
              <div
                key={`col-${colTicker}`}
                role="columnheader"
                className="flex flex-col items-center justify-end gap-1 pb-1 text-center"
              >
                <EtfChip ticker={colTicker} />
              </div>
            ))}
          </div>

          {/* Matrix rows */}
          {etfs.map((rowTicker, rowIdx) => (
            <div key={`row-${rowTicker}`} role="row" className="contents">
              <div
                role="rowheader"
                className="flex flex-col items-start justify-center gap-1 rounded-xl bg-background-secondary-default px-3 py-2"
              >
                <EtfChip ticker={rowTicker} />
                {renderRowMeta ? (
                  <div className="text-caption-1-regular text-text-secondary">
                    {renderRowMeta(rowTicker, rowIdx)}
                  </div>
                ) : null}
              </div>

              {etfs.map((colTicker, colIdx) => {
                const isDiagonal = rowIdx === colIdx;
                const value = matrix[rowIdx]?.[colIdx] ?? 0;
                const selected = !isDiagonal && isSamePair(selectedPair, rowTicker, colTicker);
                const subtitle = getCellSubtitle
                  ? getCellSubtitle(rowTicker, colTicker, value, isDiagonal)
                  : isDiagonal
                    ? diagonalCaption
                    : pairCaption;
                const title = getCellTitle
                  ? getCellTitle(rowTicker, colTicker, value, isDiagonal)
                  : isDiagonal
                    ? `${rowTicker} covered holdings weight: ${formatPct(value)}`
                    : `${rowTicker} × ${colTicker} overlap: ${formatPct(value)}`;
                const bg = heatBackground(value, isDiagonal);
                const cellKey = `${rowIdx}:${colIdx}`;

                if (isDiagonal) {
                  return (
                    <div
                      key={cellKey}
                      ref={(node) => {
                        if (node) cellRefs.current.set(cellKey, node);
                        else cellRefs.current.delete(cellKey);
                      }}
                      role="gridcell"
                      tabIndex={0}
                      title={title}
                      aria-label={title}
                      onKeyDown={(e) => handleKeyDown(e, rowIdx, colIdx)}
                      className={cx(
                        "flex min-h-[4.75rem] flex-col items-center justify-center gap-1 rounded-2xl p-2.5 text-center",
                        "border border-dashed border-border-button-default bg-background-secondary-default",
                        "outline-none focus-visible:ring-2 focus-visible:ring-border-focus-ring",
                      )}
                    >
                      <Pct
                        value={value}
                        className="text-title-3-semibold text-text-secondary"
                      />
                      <span className="text-caption-1-regular text-text-tertiary">
                        {subtitle}
                      </span>
                    </div>
                  );
                }

                return (
                  <button
                    key={cellKey}
                    ref={(node) => {
                      if (node) cellRefs.current.set(cellKey, node);
                      else cellRefs.current.delete(cellKey);
                    }}
                    type="button"
                    role="gridcell"
                    aria-selected={selected}
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
                        ? "border-accent-500 ring-2 ring-accent-500"
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
                );
              })}
            </div>
          ))}
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
          Diagonal cells (<span className="text-text-secondary">dashed</span>) show each ETF’s covered holdings weight; click any off-diagonal cell to inspect that pair.
        </span>
      </div>
    </div>
  );
}
