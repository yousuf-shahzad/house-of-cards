# TELOS — the local studio suite

A fictional studio workspace built with React 19, TypeScript, Tailwind CSS v4, real free Board UI components, and original TELOS modules inspired by the public Pro previews.

## Run

```powershell
npm install
npm run dev
```

`npm run build` checks TypeScript and builds `dist/`. `npm run preview` serves the production build at the local URL it prints (normally port 4173).

## Explore

| Page                    | What works                                                                                                                                     |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `#/`                    | Product landing page and interactive chart preview                                                                                             |
| `#/about`               | Product story and principles                                                                                                                   |
| `#/pricing`             | Illustrative monthly/yearly plans and FAQs                                                                                                     |
| `#/dashboard`           | Live project metrics, sample revenue history, studio shortcuts                                                                                 |
| `#/dashboard/projects`  | Search, stage filters, column sorting, selection, bulk stage changes, pagination, filtered CSV export                                          |
| `#/dashboard/board`     | Five-stage kanban, native dragging, keyboard/touch stage menus, owner filters, compact card preference                                         |
| `#/dashboard/calendar`  | Month/week/agenda views, project deadlines, editable studio events and completion state                                                        |
| `#/dashboard/insights`  | Client value/count breakdowns, project pipeline, completion share, clickable owner/deadline workload matrix                                    |
| `#/dashboard/team`      | Fictional team with project counts and budget totals derived from assigned work                                                                |
| `#/dashboard/assistant` | Local scripted responses, progressive reveal, stop control, expandable steps, conversation history, file metadata and temporary image previews |
| `#/dashboard/settings`  | Workspace name, default calendar view, compact cards, theme control, JSON snapshot export, confirmed reset                                     |

Use Ctrl+K / Cmd+K or the header search button to find pages, projects, and actions. The notification drawer records local project/event/preference changes; read state persists.

Project drawers support owners, priorities, budgets, deadlines, progress, briefs, checklists, and comments. Save changes commits the full draft. Board moves update the same records used by the table, calendar, team, insights, and assistant.

## Data and simulation

- Everything runs locally. There is no backend, account, billing, invitation service, or AI API.
- Existing `telos:projects` records are retained and normalized for the new views. New sample projects only appear in a fresh workspace or after an explicit reset.
- Project data, studio events, activity, preferences, read state, and assistant transcripts use this browser's local storage.
- The assistant uses deterministic response templates assembled from local project records. It does not understand arbitrary questions or analyse file contents. Attachments save only names and sizes; selected images have temporary local previews.
- Project values are illustrative budgets. The revenue history is fixed sample data and is labelled separately from project-derived metrics.
- Exports respect project filters and defend CSV formula prefixes. A JSON workspace snapshot is an export, not a sync or restore service.
- Google Fonts supplies Inter, with system font fallbacks. No credentials are needed.

## Source

`main.tsx` contains the marketing pages. `suite/` contains the original workspace, shared model, board/editor/table, calendar, insights, assistant, and tools. `components/` contains free Board UI source installed through its MCP. `styles/` provides its semantic theme and composite typography. The free date picker has a small modal-embedding option, the notification centre exposes read changes, and the sidebar follows the saved workspace name.

The original Pro-inspired modules use free components and public design references; no licensed Pro component source is included.

Board UI: https://www.boardui.com/mcp
