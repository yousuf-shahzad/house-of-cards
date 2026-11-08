"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

export type ExperienceMode = "beginner" | "expert" | null;

export const TOTAL_GUIDE_STEPS = 5;

export interface ExperienceContextValue {
  /** Current mode in memory only (`null` shows the launch dialog on every load). */
  mode: ExperienceMode;
  /** Switch between `"beginner"` (`#/guide`) and `"expert"` (full app). */
  setMode: (nextMode: "beginner" | "expert", targetHash?: string) => void;
  /** Convenience booleans. */
  isBeginner: boolean;
  isExpert: boolean;
  /** Current 1-based step (1..5) in the guided walkthrough. */
  step: number;
  /** Update the current 1-based step (1..5). */
  setStep: (step: number) => void;
  /** Total number of steps in the guided walkthrough (5). */
  totalSteps: number;
  /** Switch to Full view on a specific expert route (e.g. `"#/compare"`). */
  openExpertPage: (hash?: string) => void;
  /** Switch to Simple view on `#/guide`, optionally jumping to a 1-based step. */
  openBeginnerGuide: (step?: number) => void;
}

const ExperienceContext = createContext<ExperienceContextValue | null>(null);

function clampStep(step: number): number {
  if (!Number.isFinite(step)) return 1;
  return Math.max(1, Math.min(TOTAL_GUIDE_STEPS, Math.round(step)));
}

function isGuideHash(hash: string): boolean {
  const key = hash.replace(/^#\/?/, "").split(/[/?]/)[0];
  return key === "guide";
}

export function ExperienceProvider({ children }: { children: ReactNode }) {
  // Stored in memory only: every page load starts with `null` so the welcome dialog opens.
  const [mode, setModeState] = useState<ExperienceMode>(null);
  const [step, setStepState] = useState<number>(1);
  const lastExpertHashRef = useRef<string>("#/portfolio");

  const setStep = useCallback((nextStep: number) => {
    setStepState(clampStep(nextStep));
  }, []);

  const setMode = useCallback((nextMode: "beginner" | "expert", targetHash?: string) => {
    const currentHash = window.location.hash;
    if (currentHash && !isGuideHash(currentHash)) {
      lastExpertHashRef.current = currentHash;
    }
    setModeState(nextMode);
    if (nextMode === "beginner") {
      const nextHash = targetHash ?? "#/guide";
      if (window.location.hash !== nextHash) {
        window.location.hash = nextHash;
      }
    } else {
      const nextHash =
        targetHash ??
        (!currentHash || isGuideHash(currentHash) ? lastExpertHashRef.current : currentHash);
      if (window.location.hash !== nextHash) {
        window.location.hash = nextHash;
      }
    }
  }, []);

  const openExpertPage = useCallback(
    (hash?: string) => {
      setMode("expert", hash ?? "#/portfolio");
    },
    [setMode],
  );

  const openBeginnerGuide = useCallback(
    (nextStep?: number) => {
      if (typeof nextStep === "number") {
        setStep(nextStep);
      }
      setMode("beginner", "#/guide");
    },
    [setMode, setStep],
  );

  // Sync mode when a step link navigates directly to an expert route (e.g. `#/compare`, `#/exposures`)
  // or when navigating back to `#/guide`.
  useEffect(() => {
    const onHashChange = () => {
      const currentHash = window.location.hash;
      if (!currentHash) return;
      if (isGuideHash(currentHash)) {
        const match = currentHash.match(/[?&]step=(\d+)/);
        if (match) {
          setStep(Number(match[1]));
        }
        setModeState((prev) => (prev === null ? prev : "beginner"));
      } else {
        lastExpertHashRef.current = currentHash;
        setModeState((prev) => (prev === null ? prev : "expert"));
      }
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [setStep]);

  const value = useMemo<ExperienceContextValue>(
    () => ({
      mode,
      setMode,
      isBeginner: mode === "beginner",
      isExpert: mode === "expert",
      step,
      setStep,
      totalSteps: TOTAL_GUIDE_STEPS,
      openExpertPage,
      openBeginnerGuide,
    }),
    [mode, setMode, step, setStep, openExpertPage, openBeginnerGuide],
  );

  return <ExperienceContext.Provider value={value}>{children}</ExperienceContext.Provider>;
}

export function useExperience(): ExperienceContextValue {
  const ctx = useContext(ExperienceContext);
  if (!ctx) {
    throw new Error("useExperience must be used inside ExperienceProvider");
  }
  return ctx;
}
