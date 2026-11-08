import type { PageKey } from "@/app/registry";

export const SIMPLE_COPY: Partial<Record<PageKey, { title: string; description: string; tip: string }>> = {
  portfolio: {
    title: "Your portfolio",
    description: "Start with a sample, or enter the ETFs you own.",
    tip: "An ETF is a basket of investments. Add your shares and we will look inside each basket.",
  },
  exposures: {
    title: "What you really own",
    description: "Your biggest company holdings, added up across your ETFs.",
    tip: "Owning the same company through several ETFs adds to your stake in that company.",
  },
  overlap: {
    title: "Are your ETFs repeating each other?",
    description: "See which pairs hold the most of the same companies.",
    tip: "Higher overlap means two funds are more alike. It does not measure your chance of losing money.",
  },
  dependencies: {
    title: "What your companies rely on",
    description: "A short check of suppliers, customers and countries in company reports.",
    tip: "This check covers your biggest companies. A missing link can mean the report did not disclose it.",
  },
  compare: {
    title: "Try a change",
    description: "Edit a copy of your portfolio and see what changes.",
    tip: "Your original portfolio stays saved. Try an idea or edit the copy; the comparison updates automatically.",
  },
  risk: {
    title: "How spread out is your money?",
    description: "Check your largest holdings, industries and the data behind them.",
    tip: "Many company names can still hide a big bet on one industry. Look at both company and industry totals.",
  },
};
