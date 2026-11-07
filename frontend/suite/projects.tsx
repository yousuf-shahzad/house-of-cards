import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { Button, ButtonLink } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { Textarea } from "@/components/base/textarea/textarea";
import { NumberField } from "@/components/base/number-field/number-field";
import { DatePicker } from "@/components/base/date-picker/date-picker";
import { Select, SelectItem } from "@/components/base/select/select";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Avatar } from "@/components/base/avatar/avatar";
import { Chip } from "@/components/base/badges/chip";
import { ProgressBar } from "@/components/base/progress/progress";
import { SearchField } from "@/components/base/search-field/search-field";
import {
  Table,
  TableHeader,
  TableColumn,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/base/table/table";
import {
  Drawer,
  DrawerHeader,
  DrawerBody,
  DrawerFooter,
} from "@/components/base/drawer/drawer";
import { parseDate } from "@internationalized/date";
import {
  RiAddLine,
  RiArrowRightLine,
  RiFolder3Line,
  RiDragMove2Line,
  RiChat1Line,
} from "@remixicon/react";
import { cx } from "@/utils/cx";
import {
  STAGES,
  people,
  money,
  tone,
  dueOf,
  dateLabel,
  type Project,
  type Stage,
} from "./model";

export function ProjectEditor({
  project,
  onSave,
  onClose,
  isNew = false,
}: {
  project: Project;
  isNew?: boolean;
  onSave: (p: Project) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<Project>(() => ({
    ...project,
    checklist: [...(project.checklist || [])],
    comments: [...(project.comments || [])],
  }));
  const [task, setTask] = useState("");
  const [comment, setComment] = useState("");
  const patch = (fields: Partial<Project>) =>
    setDraft((p) => ({ ...p, ...fields }));
  return (
    <Drawer
      isOpen
      isDismissable={false}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      size="lg"
    >
      <DrawerHeader
        title={isNew ? "Make room for something new." : project.name}
        description={
          isNew
            ? "A clear brief. A shared direction."
            : "Project details, milestones, and the conversation around the work."
        }
      />
      <DrawerBody>
        <form
          id="project-editor"
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.name.trim() && draft.client.trim())
              onSave({
                ...draft,
                name: draft.name.trim(),
                client: draft.client.trim(),
                due: dateLabel(draft.dueISO || ""),
                progress: draft.status === "Completed" ? 100 : draft.progress,
              });
          }}
          className="suite-form"
        >
          <Input
            label="Project name"
            isRequired
            value={draft.name}
            onChange={(name) => patch({ name })}
            maxLength={100}
          />
          <div className="suite-field-grid">
            <Input
              label="Client or team"
              isRequired
              value={draft.client}
              onChange={(client) => patch({ client })}
              maxLength={80}
            />
            <Input
              label="Discipline"
              value={draft.category}
              onChange={(category) => patch({ category })}
              maxLength={80}
            />
          </div>
          <div className="suite-field-grid">
            <Select
              label="Project stage"
              selectedKey={draft.status}
              onSelectionChange={(key) =>
                patch({ status: String(key) as Stage })
              }
            >
              {STAGES.map((stage) => (
                <SelectItem id={stage} key={stage}>
                  {stage}
                </SelectItem>
              ))}
            </Select>
            <Select
              label="Priority"
              selectedKey={draft.priority || "Medium"}
              onSelectionChange={(key) =>
                patch({ priority: String(key) as Project["priority"] })
              }
            >
              {["Low", "Medium", "High"].map((p) => (
                <SelectItem id={p} key={p}>
                  {p}
                </SelectItem>
              ))}
            </Select>
            <Select
              label="Project owner"
              selectedKey={draft.owner}
              onSelectionChange={(key) => patch({ owner: String(key) })}
            >
              {people.map((p) => (
                <SelectItem id={p.initials} key={p.initials}>
                  {p.name}
                </SelectItem>
              ))}
            </Select>
            <NumberField
              label="Budget (USD)"
              value={draft.budget}
              onChange={(budget) =>
                patch({ budget: Number.isFinite(budget) ? budget : 0 })
              }
              minValue={0}
              maxValue={100000000}
              hideSteppers
            />
          </div>
          <div className="suite-field-grid">
            <div className="flex flex-col gap-2">
              <span className="text-body-medium text-text-primary">
                Project deadline
              </span>
              <DatePicker
                modal
                aria-label="Project deadline"
                value={draft.dueISO ? parseDate(draft.dueISO) : null}
                onChange={(date) => patch({ dueISO: date?.toString() || "" })}
              />
              {draft.dueISO && (
                <Button
                  variant="secondary"
                  size="xs"
                  className="w-fit"
                  onClick={() => patch({ dueISO: "" })}
                >
                  Clear deadline
                </Button>
              )}
            </div>
            <NumberField
              label="Progress (%)"
              minValue={0}
              maxValue={100}
              value={draft.progress}
              onChange={(progress) =>
                patch({ progress: Number.isFinite(progress) ? progress : 0 })
              }
            />
          </div>
          <Textarea
            label="Project brief"
            rows={3}
            value={draft.notes || ""}
            onChange={(notes) => patch({ notes })}
            placeholder="What are we making, and why does it matter?"
            maxLength={3000}
          />
          <div className="editor-section">
            <h3 className="text-headline-medium">A few clear next steps</h3>
            {draft.checklist?.map((t) => (
              <Checkbox
                key={t.id}
                isSelected={t.done}
                onChange={(done) =>
                  patch({
                    checklist: draft.checklist?.map((x) =>
                      x.id === t.id ? { ...x, done } : x,
                    ),
                  })
                }
              >
                {t.label}
              </Checkbox>
            ))}
            <div className="flex items-end gap-2">
              <Input
                label="Add a checklist item"
                value={task}
                onChange={setTask}
                maxLength={140}
                placeholder="A small step forward"
              />
              <Button
                variant="secondary"
                leadingIcon={RiAddLine}
                aria-label="Add checklist item"
                disabled={!task.trim()}
                onClick={() => {
                  patch({
                    checklist: [
                      ...(draft.checklist || []),
                      {
                        id: crypto.randomUUID(),
                        label: task.trim(),
                        done: false,
                      },
                    ],
                  });
                  setTask("");
                }}
              >
                Add
              </Button>
            </div>
          </div>
          <div className="editor-section">
            <h3 className="text-headline-medium">Studio notes</h3>
            {draft.comments?.length ? (
              draft.comments.map((c) => (
                <div key={c.id} className="project-comment">
                  <Avatar initials="AL" size="sm" color="blue" />
                  <div>
                    <span className="text-caption-1-medium text-text-primary">
                      Alex Lane · {new Date(c.date).toLocaleDateString("en-GB")}
                    </span>
                    <p className="text-body-regular text-text-secondary">
                      {c.text}
                    </p>
                  </div>
                </div>
              ))
            ) : (
              <p className="text-body-regular text-text-tertiary">
                Keep the context close to the work.
              </p>
            )}
            <Textarea
              label="Add a note"
              rows={2}
              value={comment}
              onChange={setComment}
              maxLength={1000}
            />
            <Button
              variant="secondary"
              leadingIcon={RiChat1Line}
              disabled={!comment.trim()}
              className="w-fit"
              onClick={() => {
                patch({
                  comments: [
                    ...(draft.comments || []),
                    {
                      id: crypto.randomUUID(),
                      text: comment.trim(),
                      date: new Date().toISOString(),
                    },
                  ],
                });
                setComment("");
              }}
            >
              Add note to draft
            </Button>
          </div>
          <p className="text-caption-1-regular text-text-tertiary">
            Save changes to keep this project, checklist, and notes in your
            browser.
          </p>
        </form>
      </DrawerBody>
      <DrawerFooter>
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button
          type="submit"
          form="project-editor"
          trailingIcon={RiArrowRightLine}
        >
          {isNew ? "Create project" : "Save changes"}
        </Button>
      </DrawerFooter>
    </Drawer>
  );
}

export function ProjectBoard({
  projects,
  onOpen,
  onMove,
  onNew,
  compact,
}: {
  projects: Project[];
  onOpen: (p: Project) => void;
  onMove: (id: string, status: Stage) => void;
  onNew: (stage: Stage) => void;
  compact: boolean;
}) {
  const [query, setQuery] = useState("");
  const [owner, setOwner] = useState("all");
  const [drag, setDrag] = useState<string | null>(null);
  const [over, setOver] = useState<Stage | null>(null);
  const shown = projects.filter(
    (p) =>
      (owner === "all" || p.owner === owner) &&
      `${p.name} ${p.client}`.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <>
      <div className="suite-toolbar">
        <div className="flex items-center gap-3">
          <Chip color="blue">{shown.length} projects</Chip>
          <span className="text-body-regular text-text-secondary">
            A shared view of what’s next.
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <SearchField
            aria-label="Search board"
            placeholder="Search the board…"
            value={query}
            onChange={setQuery}
          />
          <Select
            aria-label="Board owner filter"
            selectedKey={owner}
            onSelectionChange={(key) => setOwner(String(key))}
          >
            <SelectItem id="all">Everyone</SelectItem>
            {people.map((p) => (
              <SelectItem id={p.initials} key={p.initials}>
                {p.name}
              </SelectItem>
            ))}
          </Select>
          <ButtonLink variant="secondary" href="#/dashboard/projects">
            List view
          </ButtonLink>
        </div>
      </div>
      <p className="text-caption-1-regular text-text-tertiary">
        Drag a card between columns, or use its “Move to” menu with a keyboard
        or touch.
      </p>
      <div className="kanban-scroll">
        <div className={cx("kanban-board", compact && "compact")}>
          {STAGES.map((stage) => (
            <section
              key={stage}
              aria-label={`${stage} column`}
              className={cx("kanban-column", over === stage && "drag-over")}
              onDragOver={(e) => {
                if (drag) {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "move";
                  setOver(stage);
                }
              }}
              onDrop={(e) => {
                e.preventDefault();
                const id = e.dataTransfer.getData("text/telos-project");
                if (projects.some((p) => p.id === id)) onMove(id, stage);
                setDrag(null);
                setOver(null);
              }}
            >
              <div className="kanban-column-heading">
                <Chip color={tone(stage)} variant="caption">
                  {stage}
                </Chip>
                <span className="text-caption-1-medium text-text-tertiary">
                  {shown.filter((p) => p.status === stage).length}
                </span>
                <Button
                  variant="secondary"
                  size="xs"
                  iconOnly
                  leadingIcon={RiAddLine}
                  aria-label={`Add project to ${stage}`}
                  onClick={() => onNew(stage)}
                />
              </div>
              <div className="kanban-cards">
                {shown
                  .filter((p) => p.status === stage)
                  .map((p) => (
                    <article
                      key={p.id}
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData("text/telos-project", p.id);
                        e.dataTransfer.effectAllowed = "move";
                        setDrag(p.id);
                      }}
                      onDragEnd={() => {
                        setDrag(null);
                        setOver(null);
                      }}
                      className={cx(
                        "kanban-card",
                        drag === p.id && "is-dragging",
                      )}
                    >
                      <div className="flex justify-between items-center">
                        <span className="text-caption-1-medium text-text-tertiary">
                          {p.client}
                        </span>
                        <RiDragMove2Line
                          className="size-4 text-foreground-icon-tertiary"
                          aria-label="Draggable project"
                        />
                      </div>
                      <button
                        className="kanban-title text-headline-medium text-text-primary"
                        onClick={() => onOpen(p)}
                      >
                        {p.name}
                      </button>
                      <span className="text-caption-1-regular text-text-tertiary">
                        {p.category}
                      </span>
                      <ProgressBar
                        aria-label={`${p.name} progress`}
                        value={p.progress}
                        size="sm"
                      />
                      <div className="kanban-meta">
                        <Chip
                          color={p.priority === "High" ? "orange" : "neutral"}
                          variant="caption"
                        >
                          {p.priority || "Medium"}
                        </Chip>
                        <span className="text-caption-1-regular text-text-secondary">
                          {dateLabel(dueOf(p))}
                        </span>
                        <Avatar
                          initials={p.owner}
                          size="sm"
                          color={
                            people.find((x) => x.initials === p.owner)?.color
                          }
                        />
                      </div>
                      <Select
                        size="sm"
                        aria-label={`Move ${p.name} to`}
                        selectedKey={p.status}
                        onSelectionChange={(key) =>
                          onMove(p.id, String(key) as Stage)
                        }
                        triggerClassName="w-full"
                      >
                        {STAGES.map((s) => (
                          <SelectItem id={s} key={s}>
                            {s}
                          </SelectItem>
                        ))}
                      </Select>
                    </article>
                  ))}
                {!shown.some((p) => p.status === stage) && (
                  <button
                    className="kanban-empty text-body-regular text-text-tertiary"
                    onClick={() => onNew(stage)}
                  >
                    <RiAddLine className="size-5" />A little room for what’s
                    next.
                  </button>
                )}
              </div>
            </section>
          ))}
        </div>
      </div>
    </>
  );
}

export function ProjectsTable({
  projects,
  onOpen,
  onBulkMove,
  onExport,
}: {
  projects: Project[];
  onOpen: (p: Project) => void;
  onBulkMove: (ids: string[], stage: Stage) => void;
  onExport: (rows: Project[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [stage, setStage] = useState("all");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [selection, setSelection] = useState<Record<string, boolean>>({});
  const data = useMemo(
    () =>
      projects.filter(
        (p) =>
          (stage === "all" || p.status === stage) &&
          `${p.name} ${p.client} ${p.category}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [projects, query, stage],
  );
  const columns = useMemo<ColumnDef<Project>[]>(
    () => [
      {
        id: "select",
        header: "Select",
        cell: ({ row }) => (
          <Checkbox
            slot={null}
            aria-label={`Select ${row.original.name}`}
            isSelected={row.getIsSelected()}
            onChange={row.toggleSelected}
          />
        ),
      },
      {
        accessorKey: "name",
        header: "Project",
        cell: ({ row }) => (
          <button
            className="table-project-button"
            onClick={() => onOpen(row.original)}
          >
            <span className="project-icon">
              <RiFolder3Line className="size-5" />
            </span>
            <span>
              <span className="text-body-medium">{row.original.name}</span>
              <span className="text-caption-1-regular text-text-tertiary">
                {row.original.client} · {row.original.category}
              </span>
            </span>
          </button>
        ),
      },
      {
        accessorKey: "status",
        header: "Stage",
        cell: ({ row }) => (
          <Chip color={tone(row.original.status)} variant="caption">
            {row.original.status}
          </Chip>
        ),
      },
      {
        accessorKey: "progress",
        header: "Progress",
        cell: ({ row }) => (
          <div className="table-progress">
            <ProgressBar
              aria-label={`${row.original.name} completion`}
              value={row.original.progress}
              size="sm"
            />
            <span className="text-caption-1-regular">
              {row.original.progress}%
            </span>
          </div>
        ),
      },
      {
        accessorKey: "budget",
        header: "Budget",
        cell: ({ getValue }) => money(getValue<number>()),
      },
      {
        id: "deadline",
        accessorFn: (p) => dueOf(p) || "9999",
        header: "Deadline",
        cell: ({ row }) => dateLabel(dueOf(row.original)),
      },
      {
        accessorKey: "owner",
        header: "Owner",
        cell: ({ row }) => (
          <Avatar
            size="sm"
            initials={row.original.owner}
            color={people.find((p) => p.initials === row.original.owner)?.color}
          />
        ),
      },
    ],
    [onOpen],
  );
  const table = useReactTable({
    data,
    columns,
    state: { sorting, rowSelection: selection },
    onSortingChange: setSorting,
    onRowSelectionChange: setSelection,
    getRowId: (row) => row.id,
    enableRowSelection: true,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 5 } },
  });
  const selected = table
    .getFilteredSelectedRowModel()
    .rows.map((r) => r.original.id);
  return (
    <section className="projects-panel">
      <div className="projects-panel-heading">
        <div>
          <h2 className="text-headline-medium">
            All projects{" "}
            <span className="text-text-tertiary">({data.length})</span>
          </h2>
          <p className="text-caption-1-regular text-text-tertiary">
            Sort a column, select projects, or open a brief.
          </p>
        </div>
        <div className="project-controls">
          <SearchField
            aria-label="Search projects"
            placeholder="Search projects…"
            value={query}
            onChange={setQuery}
          />
          <Select
            aria-label="Filter by stage"
            selectedKey={stage}
            onSelectionChange={(key) => {
              setStage(String(key));
              table.setPageIndex(0);
            }}
          >
            <SelectItem id="all">All stages</SelectItem>
            {STAGES.map((s) => (
              <SelectItem id={s} key={s}>
                {s}
              </SelectItem>
            ))}
          </Select>
          <Button
            variant="secondary"
            onClick={() =>
              onExport(table.getSortedRowModel().rows.map((r) => r.original))
            }
          >
            Export view
          </Button>
        </div>
      </div>
      {selected.length > 0 && (
        <div className="selection-toolbar">
          <span className="text-body-medium">{selected.length} selected</span>
          <Select
            aria-label="Move selected projects"
            placeholder="Move selected to…"
            onSelectionChange={(key) => {
              onBulkMove(selected, String(key) as Stage);
              setSelection({});
            }}
          >
            {STAGES.map((s) => (
              <SelectItem id={s} key={s}>
                {s}
              </SelectItem>
            ))}
          </Select>
          <Button
            variant="secondary"
            size="small"
            onClick={() => setSelection({})}
          >
            Clear selection
          </Button>
        </div>
      )}
      <Table aria-label="Studio projects" selectionMode="none">
        <TableHeader>
          {table.getHeaderGroups()[0].headers.map((header) => (
            <TableColumn
              key={header.id}
              id={header.id}
              isRowHeader={header.id === "name"}
            >
              {header.id === "select" ? (
                <Checkbox
                  slot={null}
                  aria-label="Select all filtered projects"
                  isSelected={table.getIsAllRowsSelected()}
                  isIndeterminate={table.getIsSomeRowsSelected()}
                  onChange={table.toggleAllRowsSelected}
                />
              ) : (
                <button
                  className="text-caption-1-medium text-text-secondary"
                  disabled={!header.column.getCanSort()}
                  onClick={header.column.getToggleSortingHandler()}
                  aria-label={`Sort by ${String(header.column.columnDef.header)}`}
                >
                  {flexRender(
                    header.column.columnDef.header,
                    header.getContext(),
                  )}{" "}
                  {header.column.getIsSorted() === "asc"
                    ? "↑"
                    : header.column.getIsSorted() === "desc"
                      ? "↓"
                      : "↕"}
                </button>
              )}
            </TableColumn>
          ))}
        </TableHeader>
        <TableBody
          renderEmptyState={() => (
            <div className="empty-state">
              <RiFolder3Line className="size-8" />
              <p className="text-headline-medium">No projects here yet.</p>
              <Button
                variant="secondary"
                onClick={() => {
                  setQuery("");
                  setStage("all");
                }}
              >
                Clear filters
              </Button>
            </div>
          )}
        >
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id} id={row.id}>
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="table-pagination">
        <span className="text-caption-1-regular text-text-tertiary">
          {data.length === 0
            ? "No results"
            : `Page ${table.getState().pagination.pageIndex + 1} of ${Math.max(1, table.getPageCount())}`}
        </span>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="small"
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.previousPage()}
          >
            Previous
          </Button>
          <Button
            variant="secondary"
            size="small"
            disabled={!table.getCanNextPage()}
            onClick={() => table.nextPage()}
          >
            Next
          </Button>
        </div>
      </div>
    </section>
  );
}
