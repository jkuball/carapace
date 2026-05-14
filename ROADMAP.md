# Roadmap / Ideas

> This roadmap outlines planned features and improvements. Items are grouped by area and roughly ordered by priority within each section.

- [ ] Compaction
- [ ] image input ([plan](docs/plans/images.md))
- [ ] image output — agent tools producing images (screenshots, charts, renders)
- [ ] custom sentinel instructions for skills, e.g. moneydb: make sure that the agent only does mutations based on user approval
- [ ] forbid session to use some skills (include/exclude) — useful for cronjobs
- [ ] harden sandbox so trusted exec allowlists are meaningful (run as non-root, read-only root fs where possible, avoid command alias / path tampering) — important prerequisite for auto-approving read-only commands like `rg`, `ls`, `cat`
- [ ] an actual database backend instead of files
- [ ] a backend refactor/review might be in order
- [ ] update readme with new cronjob feature + outline goals of the project better?
- [ ] bundle a skill for carapace itself - firing jobs, creating subsessions, ... (auth? via key?)
- [ ] Multi-User Setup, better auth than a static token, api keys ?
- [ ] indicator how many commits ahead/behind the session's knowledge repo is + the ability to pull/push inside the sandbox without telling the agent
- [ ] warn user if deleting a session that has commits not pushed
- [ ] replace pull / push slash commands (that aren't really tied to the session anyway) with a global indicator how many commits ahead/behind the backend's global repo is compared to the remote repo
- [ ] "query" sessions in the sense that the sentinel should deny all write ops. like "ask" mode in copilot. maybe call them "ask" instead. sentinel needs to be told this everytime.
- [ ] speech input
- [ ] ui: lock-button to set both models at once
