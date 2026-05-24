# Persistent Context and Workspace Files

carapace does not have a separate agent memory directory in the current runtime model. Persistent context is ordinary content in the Git-backed knowledge repo: top-level workspace files, skills, and archived session snapshots.

---

## Workspace files

Top-level Markdown files in the knowledge repo define the agent's identity, user context, and policy. They are cloned into each session sandbox at `/workspace/` and loaded into the agent's system prompt at session start.

| File          | Purpose                                                                            | Agent-writable?                      |
| ------------- | ---------------------------------------------------------------------------------- | ------------------------------------ |
| `AGENTS.md`   | Master behavioral guide: what to do, safety rules, and coding/project conventions. | Yes (via `git push`, sentinel-gated) |
| `SOUL.md`     | Agent personality, tone, and boundaries.                                           | Yes (via `git push`, sentinel-gated) |
| `USER.md`     | User context and durable preferences.                                              | Yes (via `git push`, sentinel-gated) |
| `SECURITY.md` | Natural-language security policy for the sentinel agent.                           | Yes (via `git push`, sentinel-gated) |

## Archived sessions

When session commit/autosave is enabled, conversation snapshots are written into the knowledge repo under `sessions/YYYY/MM/<session_id>/conversation.json`. These archives are plain files, so the agent can search them with tools such as `rg` when it needs prior context.

Session runtime state still lives under `$CARAPACE_DATA_DIR/sessions/`; archived session files are the Git-backed copy intended for long-term recall and review.

## How editing works

1. On container creation, the knowledge repo is Git-cloned into the session's `/workspace/` directory.
2. The agent can edit working-copy files inside the sandbox with `read`, `write`, `str_replace`, and `exec`.
3. To make changes permanent, the agent uses `git add`, `git commit`, and `git push` inside the sandbox.
4. Every push is evaluated by the sentinel via a pre-receive hook. Changes that violate the security policy are denied or escalated for user approval.

## System prompt loading

When an agent turn starts, `build_system_prompt()` loads the following into the system prompt:

1. `AGENTS.md` — behavioral guide
2. `SOUL.md` — personality
3. `USER.md` — context about the human
4. Skill catalog — names and descriptions only
5. Sandbox environment info — explains container paths and available tools
6. Session ID
