import { useState } from "react";
import { Chip } from "@/components/base/badges/chip";
import { Avatar } from "@/components/base/avatar/avatar";
import { Select, SelectItem } from "@/components/base/select/select";
import { ProgressCircle } from "@/components/base/progress/progress";
import { Button } from "@/components/base/buttons/button";
import { people, STAGES, money, tone, dueOf, type Project } from "./model";
import { RiArrowRightUpLine, RiBarChartBoxLine } from "@remixicon/react";
import { cx } from "@/utils/cx";
export function StudioInsights({
  projects,
  onOpen,
}: {
  projects: Project[];
  onOpen: (p: Project) => void;
}) {
  const [scope, setScope] = useState("all");
  const [showAll, setShowAll] = useState(false);
  const [metric, setMetric] = useState("budget");
  const data = projects.filter(
    (p) =>
      scope === "all" ||
      (scope === "active"
        ? p.status !== "Completed"
        : p.status === "Completed"),
  );
  const total = data.reduce((s, p) => s + p.budget, 0);
  const clients = Object.entries(
    data.reduce<Record<string, number>>(
      (s, p) => ({
        ...s,
        [p.client]: (s[p.client] || 0) + (metric === "budget" ? p.budget : 1),
      }),
      {},
    ),
  ).sort((a, b) => b[1] - a[1]);
  const maximum = Math.max(...clients.map((x) => x[1]), 1);
  const maxStage = Math.max(
    ...STAGES.map((s) => data.filter((p) => p.status === s).length),
    1,
  );
  const complete = projects.filter((p) => p.status === "Completed").length;
  const rate = projects.length
    ? Math.round((complete / projects.length) * 100)
    : 0;
  return (
    <>
      <div className="suite-toolbar">
        <div>
          <h2 className="text-title-2-medium">
            A clearer picture of the studio.
          </h2>
          <p className="text-body-regular text-text-secondary mt-2">
            These insights use your actual local projects and their current
            properties.
          </p>
        </div>
        <Select
          aria-label="Insights project scope"
          selectedKey={scope}
          onSelectionChange={(key) => setScope(String(key))}
        >
          <SelectItem id="all">All projects</SelectItem>
          <SelectItem id="active">Active projects</SelectItem>
          <SelectItem id="completed">Completed projects</SelectItem>
        </Select>
      </div>
      <div className="insights-grid">
        <section className="suite-card client-chart">
          <div className="suite-card-heading">
            <div>
              <span className="text-caption-1-medium text-text-tertiary">
                WHERE THE WORK COMES FROM
              </span>
              <h3 className="text-title-2-medium">By client</h3>
            </div>
            <Select
              size="sm"
              aria-label="Client chart metric"
              selectedKey={metric}
              onSelectionChange={(key) => setMetric(String(key))}
            >
              <SelectItem id="budget">Project value</SelectItem>
              <SelectItem id="count">Project count</SelectItem>
            </Select>
          </div>
          <span className="text-display-3-medium">
            {metric === "budget" ? money(total) : data.length}
            <span className="text-body-regular text-text-tertiary">
              {" "}
              {metric === "budget" ? "contracted value" : "projects"}
            </span>
          </span>
          <div
            className="ranked-bars"
            role="list"
            aria-label="Projects by client"
          >
            {clients
              .slice(0, showAll ? undefined : 5)
              .map(([name, value], i) => (
                <div role="listitem" key={name} className="ranked-row">
                  <span
                    className="ranked-fill"
                    style={{ width: `${(value / maximum) * 100}%` }}
                  />
                  <span className="text-body-medium">
                    <span className="text-text-tertiary me-3">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    {name}
                  </span>
                  <span className="text-body-medium">
                    {metric === "budget" ? money(value) : value}
                  </span>
                </div>
              ))}
          </div>
          {clients.length === 0 && (
            <p className="suite-empty text-body-regular text-text-tertiary">
              No projects in this view yet.
            </p>
          )}
          {clients.length > 5 && (
            <Button
              variant="secondary"
              size="small"
              className="w-fit"
              onClick={() => setShowAll(!showAll)}
            >
              {showAll ? "Show fewer" : "Show all clients"}
            </Button>
          )}
          <p className="text-caption-1-regular text-text-tertiary">
            Project budgets are illustrative contract values, not recognised
            revenue.
          </p>
        </section>
        <section className="suite-card">
          <div className="suite-card-heading">
            <div>
              <span className="text-caption-1-medium text-text-tertiary">
                FROM IDEA TO HANDOFF
              </span>
              <h3 className="text-title-2-medium">Project pipeline</h3>
            </div>
            <RiBarChartBoxLine className="size-6 text-accent-600" />
          </div>
          <div className="stage-chart">
            {STAGES.map((stage) => {
              const rows = data.filter((p) => p.status === stage);
              return (
                <div key={stage}>
                  <div className="flex items-center justify-between">
                    <Chip color={tone(stage)} variant="caption">
                      {stage}
                    </Chip>
                    <span className="text-body-medium">
                      {rows.length}
                      <span className="text-caption-1-regular text-text-tertiary">
                        {" "}
                        · {money(rows.reduce((s, p) => s + p.budget, 0))}
                      </span>
                    </span>
                  </div>
                  <div className="stage-track">
                    <div
                      className={cx(
                        "stage-fill",
                        stage === "Completed" && "completed-fill",
                      )}
                      style={{ width: `${(rows.length / maxStage) * 100}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="pipeline-summary">
            <ProgressCircle
              value={rate}
              aria-label="Completed project share"
              size="lg"
            />
            <span className="text-body-medium">
              {rate}% completed
              <span className="text-caption-1-regular text-text-tertiary block">
                {complete} of {projects.length} projects have reached the finish
                line.
              </span>
            </span>
          </div>
        </section>
      </div>
      <section className="suite-card workload-card">
        <div className="suite-card-heading">
          <div>
            <span className="text-caption-1-medium text-text-tertiary">
              MAKE SPACE BEFORE YOU MAKE PLANS
            </span>
            <h3 className="text-title-2-medium">Team workload</h3>
          </div>
          <Chip variant="caption" color="blue">
            Based on project deadlines
          </Chip>
        </div>
        <p className="text-body-regular text-text-secondary">
          Active projects grouped by owner and deadline month. Open a cell to
          see the work behind it.
        </p>
        <div className="heatmap-scroll">
          <div className="workload-grid">
            <span />
            <span className="text-caption-1-medium text-text-tertiary">
              Nov 2026
            </span>
            <span className="text-caption-1-medium text-text-tertiary">
              Dec 2026
            </span>
            <span className="text-caption-1-medium text-text-tertiary">
              Jan 2027
            </span>
            <span className="text-caption-1-medium text-text-tertiary">
              Unscheduled
            </span>
            {people.map((person) => (
              <WorkloadRow
                key={person.initials}
                person={person}
                projects={projects.filter(
                  (p) =>
                    p.status !== "Completed" && p.owner === person.initials,
                )}
                onOpen={onOpen}
              />
            ))}
          </div>
        </div>
        <div className="heatmap-key text-caption-1-regular text-text-tertiary">
          <span>Less</span>
          {[0, 1, 2, 3].map((n) => (
            <span key={n} className={cx("heatmap-swatch", `heat-${n}`)} />
          ))}
          <span>More active projects</span>
          <span className="ms-auto">
            Other dated projects remain visible on the calendar.
          </span>
        </div>
      </section>
    </>
  );
}
function WorkloadRow({
  person,
  projects,
  onOpen,
}: {
  person: (typeof people)[number];
  projects: Project[];
  onOpen: (p: Project) => void;
}) {
  const [active, setActive] = useState<number | null>(null);
  const groups = ["2026-11", "2026-12", "2027-01", ""].map((month) =>
    projects.filter((p) => (month ? dueOf(p).startsWith(month) : !dueOf(p))),
  );
  return (
    <>
      <div className="workload-person">
        <Avatar initials={person.initials} color={person.color} size="sm" />
        <span className="text-body-medium">{person.name}</span>
        <span className="text-caption-1-regular text-text-tertiary">
          {projects.length} active
        </span>
      </div>
      {groups.map((rows, i) => (
        <button
          key={i}
          className={cx(
            "heat-cell",
            `heat-${Math.min(rows.length, 3)}`,
            active === i && "active-cell",
          )}
          aria-label={`${person.name}, ${["November", "December", "January", "unscheduled"][i]}: ${rows.length} active projects`}
          onClick={() => setActive(active === i ? null : i)}
        >
          <span className="text-title-3-medium">{rows.length || "–"}</span>
        </button>
      ))}
      {active !== null && (
        <div className="workload-detail">
          {groups[active].length ? (
            groups[active].map((p) => (
              <Button
                key={p.id}
                variant="secondary"
                size="small"
                trailingIcon={RiArrowRightUpLine}
                onClick={() => onOpen(p)}
              >
                {p.name}
              </Button>
            ))
          ) : (
            <span className="text-body-regular text-text-tertiary">
              A little room for something new.
            </span>
          )}
        </div>
      )}
    </>
  );
}
