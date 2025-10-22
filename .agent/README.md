# Merak Agent Documentation Hub

Welcome to the central index for engineering documentation. This folder gives new contributors the context they need to work on Merak’s hiring agent backend.

## How the Docs Are Organised
- `System/` — architecture and system design references.
- `SOP/` — repeatable procedures (runbooks, testing checklists, migrations, etc.).
- `Tasks/` — PRDs and implementation plans for upcoming or in-flight features.

## Current Documents
| Path | Summary |
| --- | --- |
| `System/project_architecture.md` | End-to-end architecture: FastAPI entrypoints, ChatKit server flow, tooling, and configuration. |
| `chatkit_server_integration_plan.md` | Historical plan that guided the ChatKit server build; useful for context and follow-up work. |
| `SOP/chatkit_user_message_conversion.md` | How `_to_agent_input` batches history, uses `ThreadItemConverter.to_agent_input`, and when to fall back to plain text. |
| `Tasks/README.md` | Process for adding new PRDs/implementation briefs. |
| `Tasks/feat-nextjs-chatkit-frontend.md` | PRD and implementation plan for the custom Next.js ChatKit frontend. |
| `Tasks/task-chatkit-route-hardening.md` | Follow-up task to tighten `/chatkit` response handling (explicit Streaming vs NonStreaming). |

## Contributing
- Keep documents concise and focused; avoid duplicating content across files.
- Append a **Related Docs** section to every new file with links to supporting material.
- Update this index whenever you add, rename, or remove documentation.

## Related Docs
- `.agent/System/project_architecture.md` — primary reference for system architecture.
- `chatkit_server_integration_plan.md` — timeline of the ChatKit integration and open follow-ups.
- `MERAK_AGENT_PLAN.md` — phased build plan complementing the documentation here.
