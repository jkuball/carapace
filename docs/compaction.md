# Session Compaction

Long sessions eventually approach the agent model's context window. Compaction shrinks the
model history that is sent to the LLM while keeping the full human-readable transcript intact.

carapace treats compaction the same way it treats the rest of its state: nothing is hidden. The
model sees a compacted cut, but the originals stay in the events transcript and the Git-backed
session archive, and every compaction is visible in the web UI.

> v1 is **manual only** — you trigger it with `/compact`. There is no automatic trigger yet.

## What gets compacted

Three strategies operate on different regions of the history:

| Strategy | Region | What it does |
| --- | --- | --- |
| Thinking-drop | All but the newest turn | Removes stale `thinking` parts (providers do not need them back). Free, no LLM call. |
| Tool-return compaction | Kept turns, excluding the verbatim hot zone | Summarizes large tool outputs (e.g. log/`kubectl` dumps) in place. The tool call/return pairing is preserved; the part is marked so it is never compacted twice. |
| Message-fold | Turns older than the keep-window `K` | Collapses whole turns (user + assistant + tool returns) into one summary block. |

The newest `verbatim_tool_turns` completed turns form a **verbatim hot zone**: their tool outputs are
never summarized, so the agent keeps exact fidelity on its most recent work. Tool-return compaction
only touches outputs in kept turns *older* than that zone (and never inside a fold block). Set it to
`0` to allow compacting every kept tool output, including the latest turn's.

Folds are **append-only**: each `/compact` adds a new summary block rather than re-summarizing
existing ones, so summaries do not drift through repeated compaction. Adjacent blocks can later be
merged by a consolidation pass when they themselves grow large (a "tree" of summaries).

The model is always told that content was compacted: folded blocks become a clearly marked summary
message, and compacted tool outputs are prefixed with a note that the full output can be obtained by
re-running the tool.

## The `/compact` command

```
/compact            Run the full ladder: drop stale thinking → fold turns older than K → summarize big tool outputs
/compact 4          Same, but keep the last 4 completed turns verbatim
/compact fold       Only fold old turns (default K)
/compact fold 8     Only fold, keeping the last 8 turns
/compact tools      Only summarize large tool outputs in the kept region
```

`K` is a count of completed turns to keep verbatim. When omitted, `/compact` (and `/compact fold`)
use the configured default `keep_turns` (see Configuration below); passing a number overrides it for
that run only. The reply shows tokens before/after and a breakdown of what was compacted.

## Configuration

Compaction is configured per platform in **Settings → Platform → Compaction** (admin only). The
values are stored in the DB-backed platform settings (the `agent` scalar row), not a config file:

| Setting | Default | Meaning |
| --- | --- | --- |
| Compaction model | Default (title model) | Model used for fold/tool summaries |
| Keep recent turns (K) | 6 | Completed turns kept verbatim; also the default `K` for `/compact` |
| Verbatim tool turns | 2 | Newest turns whose tool outputs are never summarized (`0` disables) |
| Tool-output floor (tokens) | 500 | Tool outputs smaller than this are left alone |
| Max parallel summaries | 6 | Concurrency for tool-output summarization |

The compaction model is a separate, configurable model (a cheap/haiku-class model is a good
default); leaving it on "Default" reuses the title model. Its usage is tracked under the
`compaction` category, separate from the agent. The code defaults live in `agent.compaction`
(`AgentConfig` / `CompactionConfig`).

## Viewing compaction in the UI

- **Tool rows** that were compacted show a `compacted` badge with the method and token savings.
- **Folded turns** collapse into an expandable "N earlier messages compacted" block — expand it to
  read the original messages.
- **Agent view** (the eye icon in the session inspector) opens a read-only overlay rendering the
  model history exactly as the agent sees it: fold summaries in place of collapsed turns and
  short-form compacted tool returns. Useful for debugging what the model actually receives.

## Data model

- Model history (`session_history`) holds the compacted cut: a marked synthetic message per fold,
  and shortened `ToolReturnPart`s stamped with compaction metadata (the re-compaction guard).
- The compaction tree (`session_compaction`) stores the summary nodes for the UI and consolidation.
- The events transcript retains the originals and carries per-event compaction annotations; the
  Git archive keeps the untouched history. Compaction is therefore inspectable and reversible.

## Sentinel

The sentinel (security agent) keeps its own shadow conversation, which is bounded by its existing
reset threshold and is **not** affected by `/compact` in v1.
