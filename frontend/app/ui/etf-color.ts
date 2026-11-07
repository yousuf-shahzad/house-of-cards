// One colour per ETF, by its position in AnalysisResponse.etfs, so pages can match.
// There are 5 chart tokens and up to 10 ETFs, so colours repeat after the fifth.
// `dash` keeps those later ETFs distinct in line charts and graphs.
export function etfVisual(index: number): { color: string; dash?: string } {
  return {
    color: `var(--color-chart-${(index % 5) + 1})`,
    dash: index >= 5 ? "6 3" : undefined,
  };
}
