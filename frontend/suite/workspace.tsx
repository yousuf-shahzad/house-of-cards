"use client";
import { lazy, Suspense, useEffect, useState } from "react";
import { Button, ButtonLink } from "@/components/base/buttons/button";
import { Chip } from "@/components/base/badges/chip";
import { Avatar } from "@/components/base/avatar/avatar";
import {
  Drawer,
  DrawerHeader,
  DrawerBody,
} from "@/components/base/drawer/drawer";
import { Modal, ModalHeader, ModalFooter } from "@/components/base/modal/modal";
import {
  Accordion,
  AccordionItem,
} from "@/components/base/accordion/accordion";
import { ProgressBar } from "@/components/base/progress/progress";
import {
  StatCards,
  type Stat,
} from "@/components/application/dashboard/stat-cards";
import { RevenueChartCard } from "@/components/application/dashboard/revenue-chart-card";
import {
  RiAddLine,
  RiMenuLine,
  RiFolder3Line,
  RiMoneyDollarCircleLine,
  RiCheckboxCircleLine,
  RiGroupLine,
  RiArrowDownLine,
  RiArrowRightLine,
  RiFocus3Line,
  RiSparklingLine,
  RiCalendarLine,
} from "@remixicon/react";
import { cx } from "@/utils/cx";
import { ProjectBoard, ProjectEditor, ProjectsTable } from "./projects";
import { StudioCalendar } from "./calendar";
import { StudioInsights } from "./insights";
import {
  WorkspaceTools,
  WorkspaceSettings,
  defaultPreferences,
  type Preferences,
} from "./tools";
import {
  STAGES,
  initialProjects,
  initialMilestones,
  initialActivity,
  people,
  navItems,
  money,
  tone,
  readProjects,
  useStored,
  normalizeProject,
  dateLabel,
  dueOf,
  isoDate,
  downloadText,
  exportProjects,
  type Project,
  type Stage,
  type Milestone,
  type Activity,
} from "./model";
import "./suite.css";
const DashboardSidebar = lazy(() =>
  import("@/components/application/dashboard/dashboard-sidebar").then((m) => ({
    default: m.DashboardSidebar,
  })),
);
const StudioAssistant = lazy(() =>
  import("./assistant").then((m) => ({ default: m.StudioAssistant })),
);
const titles: Record<string, [string, string]> = {
  overview: [
    "A little clarity for your day.",
    "Your projects, people, and progress. All pointing in the same direction.",
  ],
  projects: [
    "Good work, in motion.",
    "A clear brief, a clear owner, and a clear next step.",
  ],
  board: [
    "Room for your next good idea.",
    "A shared rhythm, from the first spark to the final handoff.",
  ],
  calendar: [
    "Give the good work a little time.",
    "Project deadlines, studio moments, and a little space to think.",
  ],
  insights: [
    "The bigger picture.",
    "Project value, delivery stages, and the work across your team.",
  ],
  team: [
    "Different talents. One team.",
    "The fictional people behind a studio with a shared purpose.",
  ],
  assistant: [
    "A little clarity, on demand.",
    "A studio companion, simulated entirely in your browser.",
  ],
  settings: [
    "Make yourself at home.",
    "A few small preferences that make this workspace yours.",
  ],
};
const historyData = [
  { label: "Jan", current: 8100, previous: 6400 },
  { label: "Feb", current: 9800, previous: 7300 },
  { label: "Mar", current: 11200, previous: 7900 },
  { label: "Apr", current: 10600, previous: 8200 },
  { label: "May", current: 13800, previous: 9600 },
  { label: "Jun", current: 14700, previous: 10100 },
];
export function Workspace({
  route,
  notify,
}: {
  route: string;
  notify: (message: string) => void;
}) {
  const [projects, setProjects] = useState<Project[]>(readProjects);
  const [projectStorageFailed, setProjectStorageFailed] = useState(false);
  const [milestones, setMilestones, milestoneStorageFailed] = useStored<
    Milestone[]
  >("telos:milestones", initialMilestones);
  const [activity, setActivity, activityStorageFailed] = useStored<Activity[]>(
    "telos:activity",
    initialActivity,
  );
  const [preferences, setPreferences, preferenceStorageFailed] =
    useStored<Preferences>("telos:preferences", defaultPreferences);
  const [mobile, setMobile] = useState(false);
  const [editor, setEditor] = useState<{
    project: Project;
    isNew: boolean;
  } | null>(null);
  const [reset, setReset] = useState(false);
  const [revision, setRevision] = useState(0);
  const requested = route.split("/")[2] || "overview";
  const view = titles[requested] ? requested : "overview";
  const [title, description] = titles[view];
  useEffect(() => {
    setMobile(false);
  }, [route]);
  useEffect(() => {
    try {
      localStorage.setItem("telos:projects", JSON.stringify(projects));
      setProjectStorageFailed(false);
    } catch {
      setProjectStorageFailed(true);
    }
  }, [projects]);
  const storageFailed =
    projectStorageFailed ||
    milestoneStorageFailed ||
    activityStorageFailed ||
    preferenceStorageFailed;
  function record(
    title: string,
    description: string,
    projectId?: string,
    category: Activity["category"] = "activity",
  ) {
    setActivity((prev) =>
      [
        {
          id: crypto.randomUUID(),
          title,
          description,
          projectId,
          date: new Date().toISOString(),
          category,
        },
        ...prev,
      ].slice(0, 80),
    );
  }
  function open(project: Project) {
    setEditor({ project: normalizeProject(project), isNew: false });
  }
  function create(status: Stage = "In progress") {
    setEditor({
      isNew: true,
      project: {
        id: crypto.randomUUID(),
        name: "",
        client: "",
        category: "New studio project",
        budget: 0,
        status,
        progress: status === "Planned" ? 10 : 0,
        due: "Not set",
        dueISO: "",
        owner: "AL",
        priority: "Medium",
        notes: "",
        comments: [],
        checklist: [],
      },
    });
  }
  function save(project: Project) {
    const isNew = editor?.isNew;
    setProjects((prev) =>
      isNew
        ? [normalizeProject(project), ...prev]
        : prev.map((p) =>
            p.id === project.id ? normalizeProject(project) : p,
          ),
    );
    record(
      isNew ? "A new project, a fresh direction." : "A little project clarity.",
      `${project.name} · ${project.status} · ${project.owner}`,
      project.id,
    );
    setEditor(null);
    notify(
      isNew
        ? "Project created. A little room for good work."
        : "Project changes saved.",
    );
  }
  function move(ids: string[], stage: Stage) {
    const changed = projects.filter(
      (p) => ids.includes(p.id) && p.status !== stage,
    );
    if (!changed.length) return;
    setProjects((prev) =>
      prev.map((p) =>
        changed.some((x) => x.id === p.id)
          ? {
              ...p,
              status: stage,
              progress:
                stage === "Completed"
                  ? 100
                  : stage === "Backlog"
                    ? 0
                    : stage === "Planned"
                      ? 10
                      : stage === "In review"
                        ? Math.max(85, p.progress)
                        : p.progress === 100
                          ? 50
                          : p.progress,
            }
          : p,
      ),
    );
    record(
      `${changed.length === 1 ? changed[0].client : `${changed.length} projects`} moved to ${stage.toLowerCase()}.`,
      changed.map((p) => p.name).join(" · "),
      changed.length === 1 ? changed[0].id : undefined,
    );
    notify(
      `${changed.length} project${changed.length === 1 ? "" : "s"} moved to ${stage.toLowerCase()}.`,
    );
  }
  function saveMilestone(event: Milestone) {
    const exists = milestones.some((m) => m.id === event.id);
    setMilestones((prev) =>
      exists
        ? prev.map((m) => (m.id === event.id ? event : m))
        : [...prev, event],
    );
    record(
      exists ? "A studio moment updated." : "A date worth making time for.",
      `${event.name} · ${dateLabel(event.date)}${event.done ? " · Completed" : ""}`,
      event.projectId || undefined,
    );
    notify("Calendar event saved.");
  }
  function exportRows(rows: Project[]) {
    exportProjects(rows);
    notify(`Exported ${rows.length} projects.`);
  }
  function exportWorkspace() {
    const conversations = (() => {
      try {
        return JSON.parse(localStorage.getItem("telos:conversations") || "[]");
      } catch {
        return [];
      }
    })();
    downloadText(
      "telos-workspace.json",
      JSON.stringify(
        {
          version: 2,
          exportedAt: new Date().toISOString(),
          projects,
          milestones,
          activity,
          preferences,
          conversations,
        },
        null,
        2,
      ),
      "application/json",
    );
    notify("Workspace snapshot exported.");
  }
  const active = projects.filter((p) => p.status !== "Completed");
  const stats: Stat[] = [
    {
      icon: RiFolder3Line,
      label: "Active projects",
      value: String(active.length).padStart(2, "0"),
      delta: "Local",
      deltaColor: "neutral",
    },
    {
      icon: RiMoneyDollarCircleLine,
      label: "Active project value",
      value: money(active.reduce((s, p) => s + p.budget, 0)),
      delta: "Demo",
      deltaColor: "neutral",
    },
    {
      icon: RiCheckboxCircleLine,
      label: "Completed",
      value: String(projects.length - active.length).padStart(2, "0"),
      delta: "Local",
      deltaColor: "lime",
    },
    {
      icon: RiGroupLine,
      label: "Team members",
      value: "04",
      delta: "Demo",
      deltaColor: "neutral",
    },
  ];
  return (
    <div
      className={cx(
        "dashboard-shell suite-workspace",
        preferences.compact && "compact-workspace",
      )}
    >
      <div className="dashboard-sidebar-wrap">
        <Suspense fallback={<div className="sidebar-placeholder" />}>
          <DashboardSidebar
            workspaceName={preferences.name}
            selected={view}
            items={navItems}
            className="telos-sidebar"
          />
        </Suspense>
      </div>
      <Drawer
        aria-label="Workspace navigation"
        isOpen={mobile}
        onOpenChange={setMobile}
        placement="start"
        size="sm"
        className="mobile-workspace-drawer"
      >
        <DrawerHeader title={preferences.name} />
        <DrawerBody>
          <Suspense
            fallback={<p className="text-body-regular">Opening workspace…</p>}
          >
            <DashboardSidebar
              workspaceName={preferences.name}
              selected={view}
              items={navItems}
              mobile
              fluid
              flat
              onClose={() => setMobile(false)}
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
              aria-label="Open workspace navigation"
              onClick={() => setMobile(true)}
            />
            <a href="#/" className="text-body-medium text-text-secondary">
              TELOS
            </a>
            <span className="text-text-tertiary">/</span>
            <span className="text-body-medium text-text-primary">
              {preferences.name}
            </span>
            <Chip variant="caption" color="blue">
              Local demo
            </Chip>
          </div>
          <div className="workspace-header-right">
            <WorkspaceTools
              key={revision}
              projects={projects}
              activity={activity}
              onNew={() => create()}
              onOpen={open}
              notify={notify}
            />
            <Avatar initials="AL" color="blue" />
          </div>
        </header>
        <main id="main" tabIndex={-1} className="dashboard-body">
          <div className="dashboard-heading">
            <div>
              <div className="text-caption-1-medium text-text-tertiary">
                {preferences.name.toUpperCase()} / {view.toUpperCase()}
              </div>
              <h1 className="text-display-4-medium">{title}</h1>
              <p className="text-body-regular text-text-secondary">
                {description}
              </p>
            </div>
            {!["assistant", "settings"].includes(view) && (
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  leadingIcon={RiArrowDownLine}
                  onClick={() => exportRows(projects)}
                >
                  Export projects
                </Button>
                <Button
                  leadingIcon={RiAddLine}
                  onClick={() =>
                    create(view === "board" ? "Backlog" : "In progress")
                  }
                >
                  New project
                </Button>
              </div>
            )}
          </div>
          {storageFailed && (
            <div className="demo-notice text-body-regular" role="status">
              Browser storage is unavailable for part of the workspace. Those
              changes will last until this page reloads.
            </div>
          )}
          {["overview", "projects", "insights"].includes(view) && (
            <StatCards stats={stats} />
          )}
          {view === "overview" && (
            <>
              <div className="dashboard-chart-grid">
                <RevenueChartCard
                  title="Sample revenue · H1 2026"
                  data={historyData}
                  className="border border-border-button-default"
                />
                <section className="focus-card">
                  <div className="flex items-center justify-between">
                    <h2 className="text-headline-medium">A little focus</h2>
                    <RiFocus3Line className="size-5 text-accent-600" />
                  </div>
                  <p className="text-body-regular text-text-secondary">
                    The next conversations worth having.
                  </p>
                  {active.slice(0, 3).map((p) => (
                    <button
                      className="focus-row"
                      key={p.id}
                      onClick={() => open(p)}
                    >
                      <div className="flex justify-between gap-2">
                        <span className="text-body-medium">{p.client}</span>
                        <Chip color={tone(p.status)} variant="caption">
                          {p.status}
                        </Chip>
                      </div>
                      <span className="text-caption-1-regular text-text-tertiary">
                        {p.name}
                      </span>
                      <ProgressBar
                        value={p.progress}
                        aria-label={`${p.name} progress`}
                        size="sm"
                      />
                    </button>
                  ))}
                  {active.length === 0 && (
                    <p className="text-body-regular text-text-tertiary">
                      Everything has reached the finish line. Make room for
                      something new.
                    </p>
                  )}
                  <ButtonLink
                    href="#/dashboard/board"
                    variant="secondary"
                    trailingIcon={RiArrowRightLine}
                    className="w-fit"
                  >
                    Open the board
                  </ButtonLink>
                </section>
              </div>
              <p className="text-caption-1-regular text-text-tertiary">
                The revenue chart is fixed sample history. Project metrics,
                board, deadlines, and workload use your local edits.
              </p>
              <div className="overview-shortcuts">
                <a href="#/dashboard/calendar">
                  <RiCalendarLine />
                  <span className="text-headline-medium">
                    Give the work a date.
                    <span className="text-body-regular text-text-secondary">
                      {milestones.filter((m) => !m.done).length} open studio
                      events · {active.filter((p) => dueOf(p)).length} dated
                      active projects
                    </span>
                  </span>
                  <RiArrowRightLine />
                </a>
                <a href="#/dashboard/assistant">
                  <RiSparklingLine />
                  <span className="text-headline-medium">
                    A fresh perspective.
                    <span className="text-body-regular text-text-secondary">
                      Try the local studio assistant
                    </span>
                  </span>
                  <RiArrowRightLine />
                </a>
              </div>
              <ProjectsTable
                projects={projects}
                onOpen={open}
                onBulkMove={move}
                onExport={exportRows}
              />
            </>
          )}
          {view === "projects" && (
            <ProjectsTable
              projects={projects}
              onOpen={open}
              onBulkMove={move}
              onExport={exportRows}
            />
          )}
          {view === "board" && (
            <ProjectBoard
              projects={projects}
              onOpen={open}
              onMove={(id, status) => move([id], status)}
              onNew={create}
              compact={preferences.compact}
            />
          )}
          {view === "calendar" && (
            <StudioCalendar
              key={`${revision}-${preferences.calendarView}`}
              projects={projects}
              milestones={milestones}
              onSave={saveMilestone}
              onOpen={open}
              defaultView={preferences.calendarView}
            />
          )}
          {view === "insights" && (
            <>
              <StudioInsights projects={projects} onOpen={open} />
              <Accordion>
                <AccordionItem
                  id="chart"
                  title="Explore the sample revenue chart"
                >
                  <RevenueChartCard
                    title="Illustrative revenue history · H1 2026"
                    data={historyData}
                  />
                  <p className="text-caption-1-regular text-text-tertiary mt-3">
                    Fixed demo data, kept separate from the live local project
                    metrics.
                  </p>
                </AccordionItem>
              </Accordion>
            </>
          )}
          {view === "team" && (
            <>
              <div className="team-banner">
                <RiGroupLine className="size-10 text-accent-600" />
                <div>
                  <h2 className="text-title-2-medium">{preferences.name}</h2>
                  <p className="text-body-regular text-text-secondary">
                    Different talents. One shared direction.
                  </p>
                </div>
                <Chip color="blue">4 demo members</Chip>
              </div>
              <div className="team-grid">
                {people.map((person) => (
                  <article key={person.initials} className="person-card">
                    <Avatar
                      initials={person.initials}
                      color={person.color}
                      size="lg"
                    />
                    <h2 className="text-title-2-medium">{person.name}</h2>
                    <p className="text-body-regular text-text-secondary">
                      {person.role}
                    </p>
                    <div className="plan-divider" />
                    <span className="text-body-medium">
                      {active.filter((p) => p.owner === person.initials).length}{" "}
                      active projects
                    </span>
                    <span className="text-caption-1-regular text-text-tertiary">
                      {money(
                        active
                          .filter((p) => p.owner === person.initials)
                          .reduce((s, p) => s + p.budget, 0),
                      )}{" "}
                      project value
                    </span>
                    <ButtonLink
                      variant="secondary"
                      size="small"
                      href="#/dashboard/board"
                    >
                      Explore the work
                    </ButtonLink>
                  </article>
                ))}
              </div>
              <p className="text-body-regular text-text-tertiary">
                This is a fictional team. Its project counts follow the owners
                assigned in your project briefs.
              </p>
            </>
          )}
          {view === "assistant" && (
            <Suspense
              fallback={
                <div className="suite-empty text-body-regular">
                  Finding a little clarity…
                </div>
              }
            >
              <StudioAssistant
                key={revision}
                projects={projects}
                milestones={milestones}
                notify={notify}
              />
            </Suspense>
          )}
          {view === "settings" && (
            <WorkspaceSettings
              key={revision}
              preferences={preferences}
              onSave={(value) => {
                setPreferences(value);
                record(
                  "A workspace that feels a little more yours.",
                  "Local workspace preferences updated.",
                  undefined,
                  "system",
                );
                notify("Workspace preferences saved.");
              }}
              onReset={() => setReset(true)}
              onExport={exportWorkspace}
            />
          )}
          <footer className="dashboard-footer text-caption-1-regular text-text-tertiary">
            <span>A little less noise. A little more TELOS.</span>
            <Button
              variant="secondary"
              size="xs"
              onClick={() => setReset(true)}
            >
              Reset demo data
            </Button>
          </footer>
        </main>
      </div>
      {editor && (
        <ProjectEditor
          key={editor.project.id}
          project={editor.project}
          isNew={editor.isNew}
          onSave={save}
          onClose={() => setEditor(null)}
        />
      )}
      <Modal isOpen={reset} onOpenChange={setReset}>
        <ModalHeader
          title="A clean slate?"
          description="This restores the sample projects, studio events, preferences, activity, and assistant history in this browser. Export a workspace snapshot first if you want to keep your edits."
        />
        <ModalFooter>
          <Button variant="secondary" onClick={() => setReset(false)}>
            Keep my workspace
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              setProjects(initialProjects.map(normalizeProject));
              setMilestones(initialMilestones);
              setActivity(initialActivity);
              setPreferences(defaultPreferences);
              try {
                localStorage.removeItem("telos:conversations");
                localStorage.removeItem("telos:read-activity");
              } catch {}
              setRevision((v) => v + 1);
              setReset(false);
              notify("Demo workspace reset. A fresh perspective.");
            }}
          >
            Reset demo
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
}
