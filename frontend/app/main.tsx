import { createRoot } from "react-dom/client";
import { DirectionProvider } from "@/components/foundations/direction/direction";
import "@/styles/globals.css";
import "@/site.css";
import "@/suite/suite.css";
import { AnalysisProvider } from "./analysis";
import { ExperienceProvider } from "./experience";
import { WelcomeDialog } from "./onboarding/welcome-dialog";
import { ScenarioProvider } from "./scenario";
import { Workspace } from "./workspace";

createRoot(document.getElementById("root")!).render(
  <DirectionProvider locale="en-GB">
    <a
      className="skip-link"
      href="#main"
      onClick={(event) => {
        event.preventDefault();
        document.getElementById("main")?.focus();
      }}
    >
      Skip to content
    </a>
    <AnalysisProvider>
      <ScenarioProvider>
        <ExperienceProvider>
          <WelcomeDialog />
          <Workspace />
        </ExperienceProvider>
      </ScenarioProvider>
    </AnalysisProvider>
  </DirectionProvider>,
);
