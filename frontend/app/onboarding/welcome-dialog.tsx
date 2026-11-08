"use client";

import { RiCompass3Line, RiLayoutGridLine } from "@remixicon/react";
import { Modal, ModalBody, ModalHeader } from "@/components/base/modal/modal";
import { useExperience } from "@/app/experience";

export function WelcomeDialog() {
  const { mode, setMode } = useExperience();

  return (
    <Modal
      isOpen={mode === null}
      isDismissable={false}
      isKeyboardDismissDisabled
      size="lg"
      role="dialog"
      aria-label="Welcome to House of Cards"
    >
      <ModalHeader
        title="Welcome to House of Cards"
        description="Have you analysed an ETF portfolio before?"
        showCloseButton={false}
      />
      <ModalBody className="pb-2">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <button
            type="button"
            autoFocus
            data-testid="welcome-choice-beginner"
            onClick={() => setMode("beginner")}
            className="group flex flex-col items-start gap-2 rounded-2xl border border-border-button-default bg-background-secondary-default p-5 text-left transition-colors hover:border-accent-500 hover:bg-background-tertiary-default focus-visible:ring-2 focus-visible:ring-border-focus-ring focus-visible:outline-none"
          >
            <span className="flex size-10 items-center justify-center rounded-xl bg-accent-500/10 text-accent-500">
              <RiCompass3Line className="size-5" aria-hidden />
            </span>
            <span className="text-title-5-medium text-text-primary">
              I&apos;m new: guide me
            </span>
            <span className="text-body-sm-regular text-text-secondary">
              Walk through your portfolio step by step in plain English, with an automatic supply-chain check.
            </span>
          </button>

          <button
            type="button"
            data-testid="welcome-choice-expert"
            onClick={() => setMode("expert")}
            className="group flex flex-col items-start gap-2 rounded-2xl border border-border-button-default bg-background-secondary-default p-5 text-left transition-colors hover:border-accent-500 hover:bg-background-tertiary-default focus-visible:ring-2 focus-visible:ring-border-focus-ring focus-visible:outline-none"
          >
            <span className="flex size-10 items-center justify-center rounded-xl bg-background-tertiary-default text-foreground-icon-secondary">
              <RiLayoutGridLine className="size-5" aria-hidden />
            </span>
            <span className="text-title-5-medium text-text-primary">
              I&apos;m experienced: show everything
            </span>
            <span className="text-body-sm-regular text-text-secondary">
              Open the full dashboard with all pages, company breakdowns, overlap tables and filing quotes.
            </span>
          </button>
        </div>
      </ModalBody>
    </Modal>
  );
}
