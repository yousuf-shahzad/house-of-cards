import { useEffect, useState } from "react";
import {
  RiLayoutGridLine,
  RiFolder3Line,
  RiKanbanView2,
  RiCalendarLine,
  RiBarChartBoxLine,
  RiGroupLine,
  RiSparklingLine,
  RiSettings4Line,
  RiArrowRightUpLine,
} from "@remixicon/react";
export const STAGES = [
  "Backlog",
  "Planned",
  "In progress",
  "In review",
  "Completed",
] as const;
export type Stage = (typeof STAGES)[number];
export type Project = {
  id: string;
  name: string;
  category: string;
  client: string;
  status: Stage;
  progress: number;
  budget: number;
  due: string;
  owner: string;
  dueISO?: string;
  priority?: "Low" | "Medium" | "High";
  notes?: string;
  checklist?: { id: string; label: string; done: boolean }[];
  comments?: { id: string; text: string; date: string }[];
};
export type Milestone = {
  id: string;
  name: string;
  date: string;
  kind: "Milestone" | "Meeting" | "Deadline";
  projectId: string;
  done: boolean;
};
export type Activity = {
  id: string;
  title: string;
  description: string;
  date: string;
  projectId?: string;
  category: "activity" | "system" | "mentions";
};
export const people = [
  {
    name: "Alex Lane",
    initials: "AL",
    role: "Creative director",
    color: "blue" as const,
  },
  {
    name: "Jamie Kim",
    initials: "JK",
    role: "Product designer",
    color: "lime" as const,
  },
  {
    name: "Morgan North",
    initials: "MN",
    role: "Brand designer",
    color: "pink" as const,
  },
  {
    name: "Sam Rivera",
    initials: "SR",
    role: "Studio producer",
    color: "neutral" as const,
  },
];
export const initialProjects: Project[] = [
  {
    id: "p1",
    name: "A new chapter for Forma",
    category: "Brand strategy & identity",
    client: "Forma",
    status: "In progress",
    progress: 68,
    budget: 18500,
    due: "Nov 18",
    dueISO: "2026-11-18",
    owner: "AL",
    priority: "High",
  },
  {
    id: "p2",
    name: "Good things, delivered",
    category: "E-commerce experience",
    client: "Goodkind",
    status: "In review",
    progress: 92,
    budget: 24000,
    due: "Nov 06",
    dueISO: "2026-11-06",
    owner: "JK",
    priority: "High",
  },
  {
    id: "p3",
    name: "Space to think",
    category: "Website & art direction",
    client: "Orbit",
    status: "In progress",
    progress: 42,
    budget: 12800,
    due: "Nov 24",
    dueISO: "2026-11-24",
    owner: "MN",
    priority: "Medium",
  },
  {
    id: "p4",
    name: "Less, but better",
    category: "Campaign & content",
    client: "Still",
    status: "Completed",
    progress: 100,
    budget: 9600,
    due: "Oct 28",
    dueISO: "2026-10-28",
    owner: "SR",
    priority: "Low",
  },
  {
    id: "p5",
    name: "Built for the outdoors",
    category: "Digital product design",
    client: "Fieldwork",
    status: "In progress",
    progress: 26,
    budget: 32000,
    due: "Dec 04",
    dueISO: "2026-12-04",
    owner: "AL",
    priority: "Medium",
  },
  {
    id: "p6",
    name: "The next good thing",
    category: "Discovery & positioning",
    client: "Daybreak",
    status: "Backlog",
    progress: 0,
    budget: 8400,
    due: "Not set",
    owner: "SR",
    priority: "Low",
  },
  {
    id: "p7",
    name: "Room to grow",
    category: "Website strategy",
    client: "Canopy",
    status: "Planned",
    progress: 10,
    budget: 16000,
    due: "Nov 30",
    dueISO: "2026-11-30",
    owner: "MN",
    priority: "Medium",
  },
];
export const navItems = [
  {
    key: "overview",
    label: "Overview",
    icon: RiLayoutGridLine,
    href: "#/dashboard",
  },
  {
    key: "projects",
    label: "Projects",
    icon: RiFolder3Line,
    href: "#/dashboard/projects",
  },
  {
    key: "board",
    label: "Project board",
    icon: RiKanbanView2,
    href: "#/dashboard/board",
  },
  {
    key: "calendar",
    label: "Calendar",
    icon: RiCalendarLine,
    href: "#/dashboard/calendar",
  },
  {
    key: "insights",
    label: "Insights",
    icon: RiBarChartBoxLine,
    href: "#/dashboard/insights",
  },
  { key: "team", label: "Team", icon: RiGroupLine, href: "#/dashboard/team" },
  {
    key: "assistant",
    label: "Studio assistant",
    icon: RiSparklingLine,
    href: "#/dashboard/assistant",
  },
  {
    key: "settings",
    label: "Workspace settings",
    icon: RiSettings4Line,
    href: "#/dashboard/settings",
  },
  {
    key: "website",
    label: "Back to website",
    icon: RiArrowRightUpLine,
    href: "#/",
  },
];
export const initialMilestones: Milestone[] = [
  {
    id: "m1",
    name: "Monday studio check-in",
    date: "2026-11-02",
    kind: "Meeting",
    projectId: "",
    done: false,
  },
  {
    id: "m2",
    name: "Forma concept presentation",
    date: "2026-11-12",
    kind: "Milestone",
    projectId: "p1",
    done: false,
  },
  {
    id: "m3",
    name: "Goodkind handoff",
    date: "2026-11-05",
    kind: "Meeting",
    projectId: "p2",
    done: false,
  },
];
export const initialActivity: Activity[] = [
  {
    id: "welcome",
    title: "A little more room to work.",
    description:
      "Your board, calendar, insights, and studio assistant are ready to explore.",
    date: "2026-11-02T09:00:00.000Z",
    category: "system",
  },
];
export const money = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
export const tone = (s: Stage) =>
  s === "Completed"
    ? "lime"
    : s === "In review"
      ? "purple"
      : s === "Backlog"
        ? "neutral"
        : s === "Planned"
          ? "cyan"
          : "blue";
export const isoDate = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
export const dateFromISO = (value: string) => new Date(`${value}T12:00:00`);
export const dateLabel = (value: string) =>
  value
    ? dateFromISO(value).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
      })
    : "Not set";
export function dueOf(p: Project) {
  if (p.dueISO !== undefined) return p.dueISO;
  const match = /^(\w{3}) (\d{1,2})$/.exec(p.due || "");
  if (!match) return "";
  const month = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ].indexOf(match[1]);
  return month < 0
    ? ""
    : `2026-${String(month + 1).padStart(2, "0")}-${match[2].padStart(2, "0")}`;
}
export function normalizeProject(p: Project): Project {
  return {
    ...p,
    dueISO: dueOf(p),
    priority: p.priority || "Medium",
    notes: p.notes || "",
    checklist: p.checklist || [],
    comments: p.comments || [],
  };
}
export function readProjects(): Project[] {
  try {
    const data = JSON.parse(localStorage.getItem("telos:projects") || "null");
    if (
      Array.isArray(data) &&
      data.every(
        (p) =>
          p &&
          typeof p.id === "string" &&
          typeof p.name === "string" &&
          typeof p.client === "string" &&
          typeof p.category === "string" &&
          typeof p.owner === "string" &&
          typeof p.budget === "number" &&
          Number.isFinite(p.budget) &&
          p.budget >= 0 &&
          typeof p.progress === "number" &&
          STAGES.includes(p.status),
      )
    )
      return data.map(normalizeProject);
  } catch {}
  return initialProjects.map(normalizeProject);
}
export function useStored<T>(key: string, fallback: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const parsed = JSON.parse(localStorage.getItem(key) || "null");
      if (
        parsed !== null &&
        Array.isArray(parsed) === Array.isArray(fallback) &&
        typeof parsed === typeof fallback
      )
        return parsed as T;
    } catch {}
    return fallback;
  });
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [key, value]);
  return [value, setValue, failed] as const;
}
export function downloadText(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function exportProjects(projects: Project[]) {
  const rows = [
    [
      "Project",
      "Client",
      "Status",
      "Progress",
      "Budget USD",
      "Due",
      "Owner",
      "Priority",
    ],
    ...projects.map((p) => [
      p.name,
      p.client,
      p.status,
      p.progress,
      p.budget,
      dueOf(p),
      p.owner,
      p.priority || "Medium",
    ]),
  ];
  downloadText(
    "telos-projects.csv",
    rows
      .map((row) =>
        row
          .map(
            (value) =>
              `"${String(value)
                .replace(/^[\s]*[=+@\-]/, "'$&")
                .replaceAll('"', '""')}"`,
          )
          .join(","),
      )
      .join("\r\n"),
    "text/csv;charset=utf-8",
  );
}
