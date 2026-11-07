import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import {
  CommandPalette,
  CommandPaletteItem,
  CommandPaletteSection,
} from "@/components/base/command-palette/command-palette";
import {
  NotificationCenter,
  type NotificationCenterItem,
} from "@/components/application/notification-center/notification-center";
import {
  Drawer,
  DrawerHeader,
  DrawerBody,
} from "@/components/base/drawer/drawer";
import {
  ThemeToggle,
  applyTheme,
  useThemeMode,
} from "@/components/application/theme/theme-toggle";
import { Input } from "@/components/base/input/input";
import { Switch } from "@/components/base/switch/switch";
import { Select, SelectItem } from "@/components/base/select/select";
import { Chip } from "@/components/base/badges/chip";
import {
  RiSearchLine,
  RiNotification3Line,
  RiAddLine,
  RiMoonLine,
  RiFolder3Line,
  RiDownload2Line,
} from "@remixicon/react";
import { navItems, useStored, type Activity, type Project } from "./model";
export type Preferences = {
  name: string;
  compact: boolean;
  calendarView: string;
};
export const defaultPreferences: Preferences = {
  name: "Northstar Studio",
  compact: false,
  calendarView: "month",
};
export function WorkspaceTools({
  projects,
  activity,
  onNew,
  onOpen,
  notify,
}: {
  projects: Project[];
  activity: Activity[];
  onNew: () => void;
  onOpen: (p: Project) => void;
  notify: (s: string) => void;
}) {
  const [command, setCommand] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [read, setRead] = useStored<string[]>("telos:read-activity", []);
  const theme = useThemeMode();
  const unread = activity.filter((a) => !read.includes(a.id)).length;
  const markRead = (ids: string[]) =>
    setRead((prev) => Array.from(new Set([...prev, ...ids])));
  const items: NotificationCenterItem[] = activity.map((a) => ({
    id: a.id,
    title: a.title,
    description: a.description,
    timestamp: new Date(a.date).toLocaleString("en-GB", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }),
    category: a.category,
    group: "Studio activity",
    unread: !read.includes(a.id),
    status: a.category === "system" ? "information" : "success",
    avatar:
      a.category === "activity" ? { initials: "AL", color: "blue" } : undefined,
    actions: a.projectId
      ? [{ id: a.projectId, label: "Open project" }]
      : undefined,
  }));
  return (
    <>
      <div className="workspace-tool-buttons">
        <Button
          variant="secondary"
          size="small"
          leadingIcon={RiSearchLine}
          aria-label="Open command palette"
          onClick={() => setCommand(true)}
        >
          <span className="command-label">
            Search <span className="text-text-tertiary">Ctrl K</span>
          </span>
        </Button>
        <Button
          variant="secondary"
          size="small"
          leadingIcon={RiNotification3Line}
          aria-label={`Open notifications, ${unread} unread`}
          onClick={() => setNotifications(true)}
        >
          {unread > 0 ? Math.min(unread, 99) : undefined}
        </Button>
      </div>
      <CommandPalette
        isOpen={command}
        onOpenChange={setCommand}
        placeholder="A project, a page, a little direction…"
        onAction={(key) => {
          const value = String(key);
          if (value === "new") onNew();
          else if (value === "theme")
            applyTheme(theme === "dark" ? "light" : "dark");
          else if (value.startsWith("project:")) {
            const p = projects.find((p) => p.id === value.slice(8));
            if (p) onOpen(p);
          } else location.hash = value;
        }}
      >
        <CommandPaletteSection title="A little direction">
          {navItems.map((item) => (
            <CommandPaletteItem
              id={item.href.slice(1)}
              key={item.key}
              icon={item.icon}
              textValue={item.label}
            >
              {item.label}
            </CommandPaletteItem>
          ))}
        </CommandPaletteSection>
        <CommandPaletteSection title="Quick actions">
          <CommandPaletteItem id="new" icon={RiAddLine}>
            Create a project
          </CommandPaletteItem>
          <CommandPaletteItem id="theme" icon={RiMoonLine}>
            Switch colour theme
          </CommandPaletteItem>
        </CommandPaletteSection>
        <CommandPaletteSection title="Find a project">
          {projects.map((p) => (
            <CommandPaletteItem
              id={`project:${p.id}`}
              key={p.id}
              icon={RiFolder3Line}
              textValue={`${p.name} ${p.client}`}
              description={p.client}
            >
              {p.name}
            </CommandPaletteItem>
          ))}
        </CommandPaletteSection>
      </CommandPalette>
      <Drawer isOpen={notifications} onOpenChange={setNotifications} size="md">
        <DrawerHeader
          title="A little studio activity."
          description="Local changes and a few useful updates."
        />
        <DrawerBody>
          <Button
            variant="secondary"
            size="small"
            className="mb-4"
            disabled={unread === 0}
            onClick={() => markRead(activity.map((a) => a.id))}
          >
            Mark all as read
          </Button>
          <NotificationCenter
            className="suite-notifications"
            notifications={items}
            onReadChange={markRead}
            onAction={(id, projectId) => {
              markRead([id]);
              setNotifications(false);
              const project = projects.find((p) => p.id === projectId);
              if (project) onOpen(project);
              else notify("This project is no longer in the workspace.");
            }}
          />
        </DrawerBody>
      </Drawer>
    </>
  );
}
export function WorkspaceSettings({
  preferences,
  onSave,
  onReset,
  onExport,
}: {
  preferences: Preferences;
  onSave: (p: Preferences) => void;
  onReset: () => void;
  onExport: () => void;
}) {
  const [draft, setDraft] = useState(preferences);
  return (
    <div className="settings-grid">
      <section className="suite-card">
        <h2 className="text-title-2-medium">Make yourself at home.</h2>
        <p className="text-body-regular text-text-secondary">
          Small preferences, saved on this device.
        </p>
        <form
          className="suite-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.name.trim())
              onSave({ ...draft, name: draft.name.trim() });
          }}
        >
          <Input
            label="Workspace name"
            isRequired
            value={draft.name}
            onChange={(name) => setDraft({ ...draft, name })}
            maxLength={60}
          />
          <Select
            label="Default calendar view"
            selectedKey={draft.calendarView}
            onSelectionChange={(key) =>
              setDraft({ ...draft, calendarView: String(key) })
            }
          >
            <SelectItem id="month">Month</SelectItem>
            <SelectItem id="week">Week</SelectItem>
            <SelectItem id="agenda">Agenda</SelectItem>
          </Select>
          <Switch
            isSelected={draft.compact}
            onChange={(compact) => setDraft({ ...draft, compact })}
          >
            Compact project board cards
          </Switch>
          <Button type="submit" className="w-fit">
            Save preferences
          </Button>
        </form>
      </section>
      <div className="flex flex-col gap-6">
        <section className="suite-card">
          <h2 className="text-headline-medium">A different light.</h2>
          <p className="text-body-regular text-text-secondary">
            The same familiar workspace, whichever way you see it.
          </p>
          <ThemeToggle appearance="segmented" className="w-fit" />
        </section>
        <section className="suite-card">
          <div className="flex items-center justify-between">
            <h2 className="text-headline-medium">
              Your workspace, on your device.
            </h2>
            <Chip color="blue" variant="caption">
              Local only
            </Chip>
          </div>
          <p className="text-body-regular text-text-secondary">
            Projects, calendar events, activity, preferences, and assistant
            conversations stay in this browser. You can save a JSON snapshot of
            the complete workspace.
          </p>
          <Button
            variant="secondary"
            leadingIcon={RiDownload2Line}
            className="w-fit"
            onClick={onExport}
          >
            Export workspace
          </Button>
          <div className="plan-divider" />
          <p className="text-caption-1-regular text-text-tertiary">
            A reset removes local edits and restores the sample studio. A
            confirmation appears first.
          </p>
          <Button variant="secondary" className="w-fit" onClick={onReset}>
            Reset demo data
          </Button>
        </section>
      </div>
    </div>
  );
}
