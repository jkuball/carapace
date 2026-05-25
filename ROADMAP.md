# Roadmap / Ideas

> This roadmap outlines planned features and improvements. Items are grouped by area and roughly ordered by priority within each section.

### Agent

- [ ] subagents: bundle a skill for carapace itself - firing jobs, creating subsessions, ... (auth? via key?)
- [ ] Compaction
- [ ] image input ([plan](docs/plans/images.md))
- [ ] image output — agent tools producing images (screenshots, charts, renders)

## General

- [ ] an actual database backend instead of files
- [ ] api keys, mainly for subagents

## Workspace

- [ ] direct shell access to the session's sandbox?
- [ ] indicator how many commits ahead/behind the session's knowledge repo is + the ability to pull/push inside the sandbox without telling the agent
- [ ] warn user if deleting a session that has commits not pushed
- [ ] replace pull / push slash commands (that aren't really tied to the session anyway) with a global indicator how many commits ahead/behind the backend's global repo is compared to the remote repo

## Security

- [ ] custom sentinel instructions for skills, e.g. moneydb: make sure that the agent only does mutations based on user approval
- [ ] forbid session to use some skills (include/exclude) — useful for cronjobs
- [ ] harden sandbox so trusted exec allowlists are meaningful (run as non-root, read-only root fs where possible, avoid command alias / path tampering)
