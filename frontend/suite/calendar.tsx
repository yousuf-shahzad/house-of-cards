import { useState } from "react";
import { parseDate } from "@internationalized/date";
import { Button } from "@/components/base/buttons/button";
import { Chip } from "@/components/base/badges/chip";
import { Input } from "@/components/base/input/input";
import { DatePicker } from "@/components/base/date-picker/date-picker";
import { Select, SelectItem } from "@/components/base/select/select";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@/components/base/segmented-control/segmented-control";
import {
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
} from "@/components/base/modal/modal";
import {
  RiArrowLeftSLine,
  RiArrowRightSLine,
  RiAddLine,
  RiCalendarLine,
  RiFlagLine,
  RiCheckboxCircleLine,
} from "@remixicon/react";
import { cx } from "@/utils/cx";
import {
  dateFromISO,
  isoDate,
  dateLabel,
  dueOf,
  tone,
  type Project,
  type Milestone,
} from "./model";
type CalendarItem = {
  id: string;
  name: string;
  date: string;
  kind: string;
  project?: Project;
  milestone?: Milestone;
  done: boolean;
};
export function StudioCalendar({
  projects,
  milestones,
  onSave,
  onOpen,
  defaultView = "month",
}: {
  projects: Project[];
  milestones: Milestone[];
  onSave: (m: Milestone) => void;
  onOpen: (p: Project) => void;
  defaultView?: string;
}) {
  const [anchor, setAnchor] = useState(() => new Date(2026, 10, 2, 12));
  const [view, setView] = useState(defaultView);
  const [selected, setSelected] = useState(isoDate(anchor));
  const [editing, setEditing] = useState<Milestone | null>(null);
  const [filter, setFilter] = useState("all");
  const all: CalendarItem[] = [
    ...projects
      .filter((p) => dueOf(p))
      .map((p) => ({
        id: p.id,
        name: p.name,
        date: dueOf(p),
        kind: "Project deadline",
        project: p,
        done: p.status === "Completed",
      })),
    ...milestones.map((m) => ({
      id: m.id,
      name: m.name,
      date: m.date,
      kind: m.kind,
      milestone: m,
      done: m.done,
    })),
  ];
  const items = all.filter(
    (e) =>
      filter === "all" || (filter === "projects" ? !!e.project : !!e.milestone),
  );
  const first =
    view === "week"
      ? new Date(anchor)
      : new Date(anchor.getFullYear(), anchor.getMonth(), 1, 12);
  first.setDate(first.getDate() - ((first.getDay() + 6) % 7));
  const days = Array.from({ length: view === "week" ? 7 : 42 }, (_, i) => {
    const d = new Date(first);
    d.setDate(d.getDate() + i);
    return d;
  });
  const monthEvents = items
    .filter((e) => e.date.slice(0, 7) === isoDate(anchor).slice(0, 7))
    .sort(
      (a, b) => a.date.localeCompare(b.date) || a.name.localeCompare(b.name),
    );
  const add = (date = selected) =>
    setEditing({
      id: crypto.randomUUID(),
      name: "",
      date,
      projectId: "",
      kind: "Milestone",
      done: false,
    });
  const open = (item: CalendarItem) =>
    item.project ? onOpen(item.project) : setEditing(item.milestone!);
  const shift = (delta: number) => {
    const d = new Date(anchor);
    if (view === "week") d.setDate(d.getDate() + 7 * delta);
    else d.setMonth(d.getMonth() + delta, 1);
    setAnchor(d);
    setSelected(isoDate(d));
  };
  return (
    <>
      <div className="calendar-layout">
        <section className="suite-card calendar-card">
          <div className="calendar-header">
            <div>
              <span className="text-caption-1-medium text-text-tertiary">
                A LITTLE DIRECTION FOR YOUR DAYS
              </span>
              <h2 className="text-title-1-medium">
                {anchor.toLocaleDateString("en-GB", {
                  month: "long",
                  year: "numeric",
                })}
              </h2>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                size="small"
                onClick={() => {
                  const d = new Date();
                  d.setHours(12, 0, 0, 0);
                  setAnchor(d);
                  setSelected(isoDate(d));
                }}
              >
                Today
              </Button>
              <Button
                variant="secondary"
                size="small"
                leadingIcon={RiArrowLeftSLine}
                iconOnly
                aria-label="Previous calendar period"
                onClick={() => shift(-1)}
              />
              <Button
                variant="secondary"
                size="small"
                leadingIcon={RiArrowRightSLine}
                iconOnly
                aria-label="Next calendar period"
                onClick={() => shift(1)}
              />
              <Button
                leadingIcon={RiAddLine}
                size="small"
                onClick={() => add()}
              >
                New event
              </Button>
            </div>
          </div>
          <div className="calendar-toolbar">
            <SegmentedControl
              aria-label="Calendar view"
              selectedKeys={[view]}
              onSelectionChange={(keys) => setView(String([...keys][0]))}
            >
              {["month", "week", "agenda"].map((v) => (
                <SegmentedControlItem id={v} key={v}>
                  {v[0].toUpperCase() + v.slice(1)}
                </SegmentedControlItem>
              ))}
            </SegmentedControl>
            <Select
              aria-label="Calendar event filter"
              selectedKey={filter}
              onSelectionChange={(key) => setFilter(String(key))}
            >
              <SelectItem id="all">All events</SelectItem>
              <SelectItem id="projects">Project deadlines</SelectItem>
              <SelectItem id="milestones">Studio events</SelectItem>
            </Select>
          </div>
          {view === "agenda" ? (
            <div className="calendar-agenda">
              {monthEvents.length ? (
                monthEvents.map((e) => (
                  <button
                    key={e.id}
                    className="agenda-item"
                    onClick={() => open(e)}
                  >
                    <span className="agenda-date text-headline-medium">
                      {dateLabel(e.date)}
                    </span>
                    <span>
                      <span className="text-body-medium">{e.name}</span>
                      <span className="text-caption-1-regular text-text-tertiary">
                        {e.kind} {e.project ? `· ${e.project.client}` : ""}
                      </span>
                    </span>
                    <Chip
                      color={
                        e.done
                          ? "lime"
                          : e.project
                            ? tone(e.project.status)
                            : "purple"
                      }
                      variant="caption"
                    >
                      {e.done ? "Done" : e.kind}
                    </Chip>
                  </button>
                ))
              ) : (
                <div className="suite-empty text-body-regular text-text-tertiary">
                  A little breathing room. Add an event to this month.
                </div>
              )}
            </div>
          ) : (
            <div
              className={cx("calendar-grid", view === "week" && "week-view")}
            >
              <div className="calendar-weekdays">
                {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(
                  (day) => (
                    <span
                      key={day}
                      className="text-caption-1-medium text-text-tertiary"
                    >
                      {day}
                    </span>
                  ),
                )}
              </div>
              <div className="calendar-days">
                {days.map((day) => {
                  const iso = isoDate(day);
                  const events = items.filter((e) => e.date === iso);
                  return (
                    <div
                      key={iso}
                      className={cx(
                        "calendar-day",
                        day.getMonth() !== anchor.getMonth() && "outside-month",
                        iso === selected && "selected-day",
                      )}
                    >
                      <button
                        className={cx(
                          "calendar-date text-caption-1-medium",
                          iso === isoDate(new Date()) && "is-today",
                        )}
                        aria-label={`Select ${day.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}`}
                        aria-pressed={iso === selected}
                        onClick={() => setSelected(iso)}
                        onDoubleClick={() => add(iso)}
                      >
                        {day.getDate()}
                      </button>
                      <div className="calendar-day-events">
                        {events.slice(0, view === "week" ? 8 : 2).map((e) => (
                          <button
                            key={e.id}
                            onClick={() => open(e)}
                            className={cx(
                              "calendar-event text-caption-1-medium",
                              e.done && "event-done",
                            )}
                            title={`${e.name} · ${e.kind}`}
                          >
                            <span className="event-dot" />
                            {e.name}
                          </button>
                        ))}
                        {events.length > 2 && view !== "week" && (
                          <button
                            className="text-caption-1-medium text-accent-600"
                            onClick={() => setSelected(iso)}
                          >
                            +{events.length - 2} more
                          </button>
                        )}
                      </div>
                      <span className="calendar-mobile-count text-caption-1-medium">
                        {events.length
                          ? `${events.length} event${events.length === 1 ? "" : "s"}`
                          : ""}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          <div className="calendar-key text-caption-1-regular text-text-tertiary">
            <span>
              <span className="event-dot" />
              Project deadlines and studio milestones
            </span>
            <span>Changes stay in this browser</span>
          </div>
        </section>
        <aside className="suite-card day-panel">
          <div className="flex justify-between items-center">
            <RiCalendarLine className="size-6 text-accent-600" />
            <Button
              leadingIcon={RiAddLine}
              iconOnly
              size="small"
              variant="secondary"
              aria-label="Add event on selected date"
              onClick={() => add()}
            />
          </div>
          <span className="text-caption-1-medium text-text-tertiary">
            IN FOCUS
          </span>
          <h3 className="text-title-2-medium">
            {dateFromISO(selected).toLocaleDateString("en-GB", {
              weekday: "long",
              day: "numeric",
              month: "short",
            })}
          </h3>
          <div className="day-panel-events">
            {items
              .filter((e) => e.date === selected)
              .map((e) => (
                <button
                  className="day-event"
                  key={e.id}
                  onClick={() => open(e)}
                >
                  {e.done ? (
                    <RiCheckboxCircleLine className="size-5 text-status-lime-text" />
                  ) : (
                    <RiFlagLine className="size-5 text-accent-600" />
                  )}
                  <span>
                    <span className="text-body-medium">{e.name}</span>
                    <span className="text-caption-1-regular text-text-tertiary">
                      {e.kind}
                    </span>
                  </span>
                </button>
              ))}
            {!items.some((e) => e.date === selected) && (
              <p className="text-body-regular text-text-secondary">
                Nothing on the calendar. A good day to make a little progress.
              </p>
            )}
          </div>
          <div className="plan-divider" />
          <span className="text-caption-1-medium text-text-tertiary">
            THIS MONTH
          </span>
          <span className="text-display-3-medium">
            {monthEvents.length}
            <span className="text-body-regular text-text-tertiary">
              {" "}
              scheduled
            </span>
          </span>
          <p className="text-caption-1-regular text-text-tertiary">
            Project deadlines come directly from your project briefs. Open one
            to change its date.
          </p>
        </aside>
      </div>
      {editing && (
        <EventEditor
          key={editing.id}
          event={editing}
          projects={projects}
          onClose={() => setEditing(null)}
          onSave={(event) => {
            onSave(event);
            setSelected(event.date);
            setAnchor(dateFromISO(event.date));
            setEditing(null);
          }}
        />
      )}
    </>
  );
}
function EventEditor({
  event,
  projects,
  onSave,
  onClose,
}: {
  event: Milestone;
  projects: Project[];
  onSave: (event: Milestone) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(event);
  return (
    <Modal
      isOpen
      isDismissable={false}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.name.trim() && draft.date)
            onSave({ ...draft, name: draft.name.trim() });
        }}
      >
        <ModalHeader
          title={
            event.name
              ? "A moment worth making time for."
              : "Put a little purpose on the calendar."
          }
          description="A meeting, a milestone, or a date to work towards."
        />
        <ModalBody>
          <div className="suite-form">
            <Input
              isRequired
              label="Event name"
              value={draft.name}
              maxLength={100}
              onChange={(name) => setDraft({ ...draft, name })}
            />
            <div>
              <span className="text-body-medium text-text-primary">
                Event date
              </span>
              <DatePicker
                modal
                aria-label="Event date"
                value={parseDate(draft.date)}
                onChange={(date) => {
                  if (date) setDraft({ ...draft, date: date.toString() });
                }}
                className="mt-2"
              />
            </div>
            <Select
              label="Event type"
              selectedKey={draft.kind}
              onSelectionChange={(key) =>
                setDraft({ ...draft, kind: String(key) as Milestone["kind"] })
              }
            >
              {["Milestone", "Meeting", "Deadline"].map((k) => (
                <SelectItem id={k} key={k}>
                  {k}
                </SelectItem>
              ))}
            </Select>
            <Select
              label="Related project"
              selectedKey={draft.projectId || "none"}
              onSelectionChange={(key) =>
                setDraft({
                  ...draft,
                  projectId: key === "none" ? "" : String(key),
                })
              }
            >
              <SelectItem id="none">Studio-wide</SelectItem>
              {projects.map((p) => (
                <SelectItem key={p.id} id={p.id}>
                  {p.name}
                </SelectItem>
              ))}
            </Select>
            <Checkbox
              isSelected={draft.done}
              onChange={(done) => setDraft({ ...draft, done })}
            >
              Mark this event complete
            </Checkbox>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit">Save event</Button>
        </ModalFooter>
      </form>
    </Modal>
  );
}
