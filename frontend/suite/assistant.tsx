import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { Chip } from "@/components/base/badges/chip";
import { Textarea } from "@/components/base/textarea/textarea";
import { Select, SelectItem } from "@/components/base/select/select";
import { Avatar } from "@/components/base/avatar/avatar";
import {
  FileUpload,
  formatFileSize,
} from "@/components/base/file-upload/file-upload";
import {
  Accordion,
  AccordionItem,
} from "@/components/base/accordion/accordion";
import { AgentThinking } from "@/components/application/agent-thinking/agent-thinking";
import { ComposerLoader } from "@/components/application/composer-loader/composer-loader";
import {
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
} from "@/components/base/modal/modal";
import {
  RiSparklingLine,
  RiAddLine,
  RiArrowUpLine,
  RiAttachment2,
  RiStopFill,
  RiCloseLine,
  RiCheckLine,
  RiFileTextLine,
  RiChat1Line,
  RiHistoryLine,
} from "@remixicon/react";
import { cx } from "@/utils/cx";
import {
  dueOf,
  dateLabel,
  money,
  useStored,
  type Project,
  type Milestone,
} from "./model";
type Attachment = { name: string; size: number };
type Message = {
  id: string;
  role: "user" | "assistant";
  text: string;
  attachments?: Attachment[];
  steps?: string[];
  stopped?: boolean;
};
type Conversation = { id: string; title: string; messages: Message[] };
const greeting: Conversation = {
  id: "first-light",
  title: "A little studio perspective",
  messages: [
    {
      id: "welcome",
      role: "assistant",
      text: "Hello, Alex. A little clarity goes a long way. Ask for a studio overview, an attention list, a client update, or a plan for next week.\n\nThis is a local simulation. Responses are assembled from your project data, with no AI service or backend.",
    },
  ],
};
const prompts = [
  "Give me a studio overview",
  "What needs attention?",
  "Draft a client update",
  "Plan next week",
];
function composeAnswer(
  prompt: string,
  projects: Project[],
  events: Milestone[],
  detailed: boolean,
  mode: string,
) {
  const q = prompt.toLowerCase();
  const active = projects.filter((p) => p.status !== "Completed");
  const review = projects.filter((p) => p.status === "In review");
  const unscheduled = active.filter((p) => !dueOf(p));
  const high = active.filter((p) => p.priority === "High");
  const total = active.reduce((s, p) => s + p.budget, 0);
  const named = projects.find(
    (p) =>
      q.includes(p.client.toLowerCase()) || q.includes(p.name.toLowerCase()),
  );
  const upcoming = active
    .filter((p) => dueOf(p))
    .sort((a, b) => dueOf(a).localeCompare(dueOf(b)));
  if (/client|update|email/.test(q)) {
    const p = named || review[0] || active[0];
    return p
      ? `CLIENT UPDATE DRAFT · ${p.client}\n\nHello ${p.client} team,\n\nA quick update on ${p.name}: the project is ${p.progress}% complete and currently ${p.status.toLowerCase()}.${dueOf(p) ? ` The next delivery date is ${dateLabel(dueOf(p))}.` : ""}\n\n${p.notes ? p.notes : "We’re keeping the next steps focused and the direction clear."}\n\nNext, we’ll ${p.status === "In review" ? "gather your feedback and agree the final refinements" : "align on the next milestone and share the work for review"}.\n\nBest,\nAlex & the studio\n\n${detailed ? `INTERNAL CONTEXT\nOwner: ${p.owner}. Priority: ${p.priority || "Medium"}. Budget: ${money(p.budget)}.\n\n` : ""}This is a local draft to edit and review; nothing has been sent.`
      : "There are no projects yet. Create one and I can assemble a local client-update draft.";
  }
  if (/attention|risk|block|priority/.test(q))
    return `A LITTLE ATTENTION, IN THE RIGHT PLACES\n\n${review.length} project${review.length === 1 ? " is" : "s are"} in review${review.length ? `: ${review.map((p) => p.client).join(", ")}` : "."}${review.length ? " — a good place to ask for feedback." : ""}\n\n${high.length} active project${high.length === 1 ? " has" : "s have"} high priority${high.length ? `: ${high.map((p) => p.name).join("; ")}` : "."}\n\n${unscheduled.length} active project${unscheduled.length === 1 ? " needs" : "s need"} a deadline${unscheduled.length ? `: ${unscheduled.map((p) => p.client).join(", ")}` : "."}${unscheduled.length ? " — open the brief and give the work a date." : ""}${detailed ? "\n\nSUGGESTED NEXT STEP\nConfirm review owners first, then set dates for unscheduled work. A high priority flag is a prompt for a conversation, not proof a project is at risk." : ""}`;
  if (/plan|week|next|schedule/.test(q) || mode === "planner")
    return `A PRACTICAL PLAN FOR THE NEXT STUDIO WEEK\n\n1. Close the feedback loop. ${review.length ? `Check in on ${review.map((p) => p.client).join(" and ")}.` : "Confirm what each active project needs next."}\n\n2. Protect the nearest deadlines. ${
      upcoming
        .slice(0, 3)
        .map((p) => `${p.client} (${dateLabel(dueOf(p))})`)
        .join(", ") || "There are no dated active projects yet."
    }\n\n3. Give the team clear ownership. ${active.length} active projects are assigned across the studio.\n\n4. Leave room to think. ${unscheduled.length ? `Schedule ${unscheduled.length} undated project${unscheduled.length === 1 ? "" : "s"} before promising more work.` : "Keep a little capacity free for feedback and refinements."}${detailed ? `\n\nCALENDAR CONTEXT\n${events.filter((e) => !e.done).length} studio events are open. This plan is a scripted suggestion; it hasn’t added or changed calendar events.` : ""}`;
  return `YOUR STUDIO, AT A GLANCE\n\n${active.length} active projects · ${projects.filter((p) => p.status === "Completed").length} completed · ${money(total)} in active project value.\n\n${review.length ? `${review.map((p) => p.client).join(" and ")} ${review.length === 1 ? "is" : "are"} ready for a review conversation.` : "No projects are waiting in review right now."}\n\n${upcoming[0] ? `The nearest dated active project is ${upcoming[0].name}, due ${dateLabel(dueOf(upcoming[0]))}.` : "Add project deadlines to bring the calendar into focus."}${detailed ? `\n\nIN MOTION\n${active.map((p) => `• ${p.client}: ${p.progress}% complete, ${p.status.toLowerCase()}`).join("\n") || "No active projects yet."}\n\nYour project values are illustrative budgets, not booked revenue.` : ""}\n\nThis brief uses local project records. It does not analyse attached file contents.`;
}
export function StudioAssistant({
  projects,
  milestones,
  notify,
}: {
  projects: Project[];
  milestones: Milestone[];
  notify: (text: string) => void;
}) {
  const [threads, setThreads, storageFailed] = useStored<Conversation[]>(
    "telos:conversations",
    [greeting],
  );
  const [active, setActive] = useState(threads[0]?.id || "first-light");
  const [text, setText] = useState("");
  const [mode, setMode] = useState("brief");
  const [effort, setEffort] = useState("detailed");
  const [upload, setUpload] = useState(false);
  const [attachments, setAttachments] = useState<
    (Attachment & { url?: string })[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState(0);
  const [history, setHistory] = useState(false);
  const [copyState, setCopyState] = useState("");
  const run = useRef<{
    timer: ReturnType<typeof setTimeout> | null;
    threadId: string;
    messageId: string;
    answer: string;
    stopped: boolean;
  } | null>(null);
  const urls = useRef<string[]>([]);
  const end = useRef<HTMLDivElement>(null);
  const thread = threads.find((t) => t.id === active) || threads[0] || greeting;
  useEffect(
    () => () => {
      if (run.current?.timer) clearTimeout(run.current.timer);
      urls.current.forEach(URL.revokeObjectURL);
    },
    [],
  );
  useEffect(() => {
    if (busy) end.current?.scrollIntoView({ block: "nearest" });
  }, [thread.messages.length, busy]);
  function appendAnswer(
    threadId: string,
    messageId: string,
    content: string,
    stopped = false,
  ) {
    setThreads((prev) =>
      prev.map((t) =>
        t.id === threadId
          ? {
              ...t,
              messages: t.messages.map((m) =>
                m.id === messageId ? { ...m, text: content, stopped } : m,
              ),
            }
          : t,
      ),
    );
  }
  function stop() {
    const state = run.current;
    if (state) {
      state.stopped = true;
      if (state.timer) clearTimeout(state.timer);
      setThreads((prev) =>
        prev.map((t) =>
          t.id === state.threadId
            ? {
                ...t,
                messages: t.messages.map((m) =>
                  m.id === state.messageId
                    ? {
                        ...m,
                        stopped: true,
                        text:
                          m.text ||
                          "The local simulation was stopped. Send another prompt whenever you’re ready.",
                      }
                    : m,
                ),
              }
            : t,
        ),
      );
    }
    setBusy(false);
  }
  function send(prompt = text) {
    if (!prompt.trim() || busy) return;
    const threadId = thread.id;
    const messageId = crypto.randomUUID();
    const answer = composeAnswer(
      prompt,
      projects,
      milestones,
      effort === "detailed",
      mode,
    );
    const steps = [
      "Read local project records",
      "Check stages, owners, and deadlines",
      "Prepare a studio brief",
    ];
    const user: Message = {
      id: crypto.randomUUID(),
      role: "user",
      text: prompt.trim(),
      attachments: attachments.map(({ name, size }) => ({ name, size })),
    };
    const assistant: Message = {
      id: messageId,
      role: "assistant",
      text: "",
      steps,
    };
    setThreads((prev) => {
      const current = prev.find((t) => t.id === threadId) || thread;
      return [
        ...prev.filter((t) => t.id !== threadId),
        {
          ...current,
          title: current.messages.filter((m) => m.role === "user").length
            ? current.title
            : prompt.slice(0, 45),
          messages: [...current.messages, user, assistant],
        },
      ];
    });
    setText("");
    attachments.forEach((a) => {
      if (a.url) URL.revokeObjectURL(a.url);
    });
    setAttachments([]);
    setBusy(true);
    setPhase(0);
    const state = {
      timer: null as ReturnType<typeof setTimeout> | null,
      threadId,
      messageId,
      answer,
      stopped: false,
    };
    run.current = state;
    let step = 0;
    const prepare = () => {
      if (state.stopped) return;
      step++;
      setPhase(step);
      if (step < 3) {
        state.timer = setTimeout(prepare, 420);
        return;
      }
      const words = answer.split(" ");
      let count = 0;
      const stream = () => {
        if (state.stopped) return;
        count = Math.min(count + 12, words.length);
        appendAnswer(threadId, messageId, words.slice(0, count).join(" "));
        if (count < words.length) state.timer = setTimeout(stream, 35);
        else {
          setBusy(false);
          run.current = null;
        }
      };
      stream();
    };
    state.timer = setTimeout(prepare, 420);
  }
  function newThread() {
    if (busy) return;
    const fresh = {
      id: crypto.randomUUID(),
      title: "A fresh conversation",
      messages: [],
    };
    setThreads((prev) => [fresh, ...prev]);
    setActive(fresh.id);
    setHistory(false);
    setText("");
  }
  return (
    <div className="assistant-layout">
      <aside
        className={cx(
          "suite-card assistant-history",
          history && "history-open",
        )}
      >
        <div className="suite-card-heading">
          <h2 className="text-headline-medium">Your conversations</h2>
          <Button
            size="small"
            iconOnly
            leadingIcon={RiAddLine}
            aria-label="New conversation"
            variant="secondary"
            disabled={busy}
            onClick={newThread}
          />
        </div>
        <p className="text-caption-1-regular text-text-tertiary">
          A little context, kept close.
        </p>
        {threads.map((t) => (
          <button
            key={t.id}
            aria-label={`Open conversation: ${t.title}`}
            disabled={busy}
            className={cx("thread-item", thread.id === t.id && "active-thread")}
            onClick={() => {
              setActive(t.id);
              setHistory(false);
            }}
          >
            <RiChat1Line className="size-4" />
            <span className="text-body-medium">{t.title}</span>
          </button>
        ))}
        <div className="assistant-local-note">
          <RiSparklingLine className="size-6 text-accent-600" />
          <span className="text-body-medium">
            Studio mode, no strings attached.
          </span>
          <p className="text-caption-1-regular text-text-tertiary">
            A local simulation. No API keys, accounts, or files sent anywhere.
          </p>
        </div>
      </aside>
      <section className="assistant-main">
        <div className="assistant-titlebar">
          <div className="flex items-center gap-3">
            <span className="assistant-mark">
              <RiSparklingLine className="size-6" />
            </span>
            <div>
              <h2 className="text-headline-medium">
                A little studio perspective.
              </h2>
              <p className="text-caption-1-regular text-text-tertiary">
                Scripted responses, grounded in your local projects
              </p>
            </div>
          </div>
          <Chip color="purple" variant="caption">
            Simulation
          </Chip>
          <Button
            className="assistant-history-toggle"
            variant="secondary"
            size="small"
            leadingIcon={RiHistoryLine}
            onClick={() => setHistory(!history)}
          >
            History
          </Button>
        </div>
        {storageFailed && (
          <p
            role="status"
            className="text-body-regular text-text-error-primary"
          >
            Conversation storage is unavailable. This session stays in memory.
          </p>
        )}
        <div className="assistant-messages" aria-label="Conversation">
          <div className="assistant-suggestions">
            {prompts.map((p) => (
              <button
                disabled={busy}
                key={p}
                className="text-caption-1-medium"
                onClick={() => send(p)}
              >
                {p}
              </button>
            ))}
          </div>
          {thread.messages.length === 0 && (
            <div className="assistant-empty">
              <RiSparklingLine className="size-10 text-accent-600" />
              <h3 className="text-title-1-medium">
                What could use a little clarity?
              </h3>
              <p className="text-body-regular text-text-tertiary">
                Start with a studio overview, a client update, or a plan for the
                week.
              </p>
            </div>
          )}
          {thread.messages.map((m, i) => (
            <article
              key={m.id}
              className={cx(
                "assistant-message",
                m.role === "user" && "user-message",
              )}
            >
              <Avatar
                initials={m.role === "user" ? "AL" : "T"}
                color={m.role === "user" ? "blue" : "neutral"}
                size="md"
              />
              <div className="message-body">
                <span className="text-caption-1-semibold text-text-secondary">
                  {m.role === "user" ? "Alex Lane" : "TELOS · local simulation"}
                </span>
                {m.steps && (
                  <Accordion
                    variant="divided"
                    defaultExpandedKeys={
                      busy && i === thread.messages.length - 1 ? ["work"] : []
                    }
                  >
                    <AccordionItem
                      id="work"
                      title={
                        busy && i === thread.messages.length - 1
                          ? "A little work behind the answer"
                          : m.stopped
                            ? "Simulation stopped"
                            : "Studio brief prepared"
                      }
                    >
                      <div className="assistant-steps">
                        {m.steps.map((s, index) => (
                          <div
                            key={s}
                            className="flex items-center gap-2 text-caption-1-regular text-text-secondary"
                          >
                            {busy &&
                            i === thread.messages.length - 1 &&
                            index >= phase ? (
                              <span className="step-dot" />
                            ) : (
                              <RiCheckLine className="size-4 text-status-lime-text" />
                            )}
                            {s}
                          </div>
                        ))}
                      </div>
                    </AccordionItem>
                  </Accordion>
                )}
                {!m.text && busy && i === thread.messages.length - 1 ? (
                  <AgentThinking
                    label="Finding a little clarity"
                    variant="infinity"
                    tone="accent"
                  />
                ) : (
                  <p className="message-text text-body-regular text-text-primary">
                    {m.text}
                  </p>
                )}
                {m.attachments?.map((a, index) => (
                  <span
                    key={index}
                    className="message-attachment text-caption-1-regular"
                  >
                    <RiFileTextLine className="size-4" />
                    {a.name} · {formatFileSize(a.size)}
                  </span>
                ))}
                {m.role === "assistant" && m.text && (
                  <Button
                    variant="secondary"
                    size="xs"
                    className="w-fit"
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(m.text);
                        setCopyState(m.id);
                        notify("Studio brief copied.");
                      } catch {
                        notify(
                          "Copy is unavailable. Select the response text to copy it.",
                        );
                      }
                    }}
                  >
                    {copyState === m.id ? "Copied" : "Copy response"}
                  </Button>
                )}
              </div>
            </article>
          ))}
          <div ref={end} />
        </div>
        <div className="assistant-composer-wrap">
          <ComposerLoader
            active={busy}
            radius={24}
            colors={[
              "var(--color-accent-300)",
              "var(--color-accent-500)",
              "var(--color-chart-3)",
              "var(--color-accent-300)",
            ]}
          >
            <form
              className="assistant-composer"
              onSubmit={(e) => {
                e.preventDefault();
                send();
              }}
            >
              {attachments.length > 0 && (
                <div className="composer-attachments">
                  {attachments.map((a, i) => (
                    <div key={`${a.name}-${i}`} className="attachment-tile">
                      {a.url ? (
                        <img src={a.url} alt={`Preview of ${a.name}`} />
                      ) : (
                        <RiFileTextLine className="size-5 text-accent-600" />
                      )}
                      <span className="text-caption-1-medium">
                        {a.name}
                        <span className="block text-caption-1-regular text-text-tertiary">
                          {formatFileSize(a.size)}
                        </span>
                      </span>
                      <Button
                        variant="secondary"
                        size="xs"
                        iconOnly
                        leadingIcon={RiCloseLine}
                        aria-label={`Remove ${a.name}`}
                        onClick={() => {
                          if (a.url) URL.revokeObjectURL(a.url);
                          setAttachments((prev) =>
                            prev.filter((_, n) => n !== i),
                          );
                        }}
                      />
                    </div>
                  ))}
                </div>
              )}
              <Textarea
                aria-label="Message studio assistant"
                placeholder="A question, an idea, a little direction…"
                value={text}
                onChange={setText}
                rows={2}
                maxLength={1500}
                isDisabled={busy}
              />
              <div className="composer-actions">
                <Button
                  variant="secondary"
                  leadingIcon={RiAttachment2}
                  size="small"
                  iconOnly
                  aria-label="Attach a local file"
                  disabled={busy || attachments.length >= 4}
                  onClick={() => setUpload(true)}
                />
                <Select
                  size="sm"
                  aria-label="Assistant mode"
                  selectedKey={mode}
                  onSelectionChange={(key) => setMode(String(key))}
                  isDisabled={busy}
                >
                  <SelectItem id="brief">Studio brief</SelectItem>
                  <SelectItem id="planner">Project planner</SelectItem>
                </Select>
                <Select
                  size="sm"
                  aria-label="Response detail"
                  selectedKey={effort}
                  onSelectionChange={(key) => setEffort(String(key))}
                  isDisabled={busy}
                >
                  <SelectItem id="concise">Concise</SelectItem>
                  <SelectItem id="detailed">Detailed</SelectItem>
                </Select>
                {busy ? (
                  <Button
                    variant="secondary"
                    leadingIcon={RiStopFill}
                    className="ms-auto"
                    onClick={stop}
                  >
                    Stop
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    leadingIcon={RiArrowUpLine}
                    iconOnly
                    className="ms-auto"
                    aria-label="Send message"
                    disabled={!text.trim()}
                  />
                )}
              </div>
            </form>
          </ComposerLoader>
          <div className="composer-status text-caption-1-regular text-text-tertiary">
            <span>
              <span className="live-dot" />
              {projects.length} local projects in context
            </span>
            <span>Simulated assistant · Files are not analysed</span>
          </div>
        </div>
      </section>
      <Modal isOpen={upload} onOpenChange={setUpload}>
        <ModalHeader
          title="Keep the context close."
          description="Preview an attachment locally. Only its name and size are saved in the conversation; this simulation does not read file contents."
        />
        <ModalBody>
          <FileUpload
            allowedExtensions={[
              "pdf",
              "txt",
              "md",
              "csv",
              "png",
              "jpg",
              "jpeg",
            ]}
            onUploadComplete={(file) => {
              const url = file.type.startsWith("image/")
                ? URL.createObjectURL(file)
                : undefined;
              if (url) urls.current.push(url);
              setAttachments((prev) =>
                [...prev, { name: file.name, size: file.size, url }].slice(
                  0,
                  4,
                ),
              );
              setUpload(false);
            }}
          />
        </ModalBody>
        <ModalFooter>
          <Button variant="secondary" onClick={() => setUpload(false)}>
            Cancel
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
}
