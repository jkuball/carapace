# Roadmap / Ideas

> This roadmap outlines planned features and improvements. Items are grouped by area and roughly ordered by priority within each section.

### Agent

- [ ] subagents: bundle a skill for carapace itself - firing jobs, creating subsessions, ... (auth? via key?)
- [ ] Compaction

## General

- [ ] api keys, mainly for subagents

## Security

- [ ] custom sentinel instructions for skills, e.g. moneydb: make sure that the agent only does mutations based on user approval
- [ ] forbid session to use some skills (include/exclude) — useful for cronjobs
- [ ] harden sandbox so trusted exec allowlists are meaningful (run as non-root, read-only root fs where possible, avoid command alias / path tampering)
