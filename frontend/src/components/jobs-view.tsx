"use client";

import cronstrue from "cronstrue";
import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Loader2, Pause, Play, Plus, RefreshCw, Save, Settings2, Trash2 } from "lucide-react";
import { createJob, deleteJob, listJobs, runJob, updateJob } from "@/lib/api";
import type { JobCronTrigger, JobDefinition, SessionInfo, SessionLatestJobRun } from "@/lib/types";
import { cn } from "@/lib/utils";

interface JobsViewProps {
  server: string;
  token: string;
  sessions: SessionInfo[];
  onSessionActivated: (session: SessionInfo) => void;
  requestedJobId?: string | null;
}

const CRON_EXAMPLE_EXPRESSIONS = [
  "*/15 * * * *",
  "0 * * * *",
  "0 7 * * *",
  "0 9 * * 1-5",
  "30 18 * * 1-5",
  "0 9 1 * *",
  "0 0 * * 0",
];

function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function availableTimeZones(extraTimeZones: Array<string | null | undefined> = []): string[] {
  const values = new Set<string>(["UTC"]);
  for (const timeZone of extraTimeZones) {
    if (typeof timeZone === "string" && timeZone.trim()) {
      values.add(timeZone.trim());
    }
  }

  if (typeof Intl.supportedValuesOf === "function") {
    for (const timeZone of Intl.supportedValuesOf("timeZone")) {
      values.add(timeZone);
    }
  }

  return Array.from(values).sort((left, right) => left.localeCompare(right));
}

function createEmptyTrigger(timeZone: string): JobCronTrigger {
  return {
    type: "cron",
    expression: "",
    timezone: timeZone,
  };
}

function createEmptyJob(): JobDefinition {
  return {
    id: "",
    name: "",
    enabled: true,
    triggers: [],
    prompt: "",
    unattended: true,
    persistent_session_id: null,
  };
}

function summarizeJob(job: JobDefinition): string {
  if (job.triggers.length === 0) {
    return "On-demand only";
  }

  if (job.triggers.length === 1) {
    const [trigger] = job.triggers;
    const expression = trigger.expression.trim();
    if (!expression) {
      return "1 cron trigger";
    }

    try {
      return cronstrue.toString(expression, {
        throwExceptionOnParseError: true,
        use24HourTimeFormat: true,
      });
    } catch {
      return "1 cron trigger";
    }
  }

  const count = job.triggers.length;
  return `${count} cron trigger${count === 1 ? "" : "s"}`;
}

function normalizeJobDraft(draft: JobDefinition): JobDefinition {
  return {
    ...draft,
    id: draft.id.trim(),
    name: draft.name.trim(),
    prompt: draft.prompt.trim(),
    persistent_session_id: draft.persistent_session_id?.trim() || null,
    triggers: draft.triggers.map((trigger) => ({
      type: "cron" as const,
      expression: trigger.expression.trim(),
      timezone: trigger.timezone?.trim() || null,
    })),
  };
}

function validateJobDraft(draft: JobDefinition): string | null {
  if (!draft.id.trim()) return "Job id is required.";
  if (!draft.name.trim()) return "Job name is required.";
  if (!draft.prompt.trim()) return "Prompt is required.";

  const persistentSessionId = draft.persistent_session_id?.trim();
  if (persistentSessionId && draft.unattended) {
    return "Persistent-session jobs must be attended.";
  }

  const emptyTrigger = draft.triggers.find((trigger) => !trigger.expression.trim());
  if (emptyTrigger) return "Cron expressions must not be empty.";

  const invalidTrigger = draft.triggers.find((trigger) => describeCronExpression(trigger.expression)?.invalid);
  if (invalidTrigger) return `Cron expression is invalid: ${invalidTrigger.expression}.`;

  return null;
}

function formatSessionOption(session: SessionInfo): string {
  const label = session.title?.trim();
  if (!label) return session.session_id;
  return `${label} (${session.session_id})`;
}

function toKebabCaseId(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function describeCronExpression(expression: string): { text: string; invalid: boolean } | null {
  const trimmed = expression.trim();
  if (trimmed.length === 0) {
    return null;
  }

  try {
    return {
      text: cronstrue.toString(trimmed, {
        throwExceptionOnParseError: true,
        use24HourTimeFormat: true,
      }),
      invalid: false,
    };
  } catch {
    return {
      text: "Invalid cron expression.",
      invalid: true,
    };
  }
}

function formatInvocationTimestamp(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return value;
  }

  return new Date(parsed).toLocaleString();
}

function formatTriggerKindLabel(triggerKind: SessionLatestJobRun["trigger_kind"]): string {
  switch (triggerKind) {
    case "cron":
      return "Scheduled";
    case "api":
      return "Manual";
    case "manual":
      return "Manual";
    default:
      return triggerKind;
  }
}

export function JobsView({ server, token, sessions, onSessionActivated, requestedJobId }: JobsViewProps) {
  const [detectedTimeZone] = useState(() => browserTimeZone());
  const [jobs, setJobs] = useState<JobDefinition[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | "new">("new");
  const [draft, setDraft] = useState<JobDefinition>(createEmptyJob);
  const [isIdAutogenerated, setIsIdAutogenerated] = useState(true);
  const [openTriggerExamples, setOpenTriggerExamples] = useState<number | null>(null);
  const [runData, setRunData] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const selectedJobIdRef = useRef<string | "new">("new");
  const appliedRequestedJobIdRef = useRef<string | null>(null);
  const openTriggerExamplesRef = useRef<HTMLDivElement | null>(null);

  const selectableSessions = useMemo(
    () => sessions.filter((session) => !session.attributes.unattended && !session.attributes.archived),
    [sessions],
  );
  const timeZoneOptions = useMemo(
    () => availableTimeZones([detectedTimeZone, ...draft.triggers.map((trigger) => trigger.timezone)]),
    [detectedTimeZone, draft.triggers],
  );
  const selectedJob = useMemo(
    () => (selectedJobId === "new" ? null : jobs.find((job) => job.id === selectedJobId) ?? null),
    [jobs, selectedJobId],
  );
  const selectedJobInvocations = useMemo(
    () => {
      if (!selectedJob) {
        return [];
      }

      return sessions
        .filter((session) => session.latest_job_run?.job_id === selectedJob.id)
        .sort((left, right) => {
          const leftTime = Date.parse(left.latest_job_run?.triggered_at ?? left.last_active);
          const rightTime = Date.parse(right.latest_job_run?.triggered_at ?? right.last_active);
          const normalizedLeft = Number.isNaN(leftTime) ? 0 : leftTime;
          const normalizedRight = Number.isNaN(rightTime) ? 0 : rightTime;
          return normalizedRight - normalizedLeft;
        });
    },
    [selectedJob, sessions],
  );
  const cronExamples = useMemo(
    () => CRON_EXAMPLE_EXPRESSIONS.map((expression) => ({
      expression,
      description: cronstrue.toString(expression, {
        throwExceptionOnParseError: true,
        use24HourTimeFormat: true,
      }),
    })),
    [],
  );
  const normalizedDraft = useMemo(() => normalizeJobDraft(draft), [draft]);
  const draftValidationError = useMemo(() => validateJobDraft(normalizedDraft), [normalizedDraft]);
  const isDraftDirty = useMemo(() => {
    const baseline = selectedJob ? normalizeJobDraft(selectedJob) : createEmptyJob();
    return JSON.stringify(normalizedDraft) !== JSON.stringify(baseline);
  }, [normalizedDraft, selectedJob]);
  const visibleError = error ?? (isDraftDirty ? draftValidationError : null);

  function selectJob(nextJobs: JobDefinition[], nextSelectedJobId: string | "new"): void {
    if (nextSelectedJobId === "new") {
      selectedJobIdRef.current = "new";
      setSelectedJobId("new");
      setDraft(createEmptyJob());
      setIsIdAutogenerated(true);
      setOpenTriggerExamples(null);
      setRunData("");
      return;
    }

    const selectedJob = nextJobs.find((job) => job.id === nextSelectedJobId) ?? nextJobs[0];
    if (!selectedJob) {
      selectedJobIdRef.current = "new";
      setSelectedJobId("new");
      setDraft(createEmptyJob());
      setIsIdAutogenerated(true);
      setOpenTriggerExamples(null);
      setRunData("");
      return;
    }

    selectedJobIdRef.current = selectedJob.id;
    setSelectedJobId(selectedJob.id);
    setDraft(structuredClone(selectedJob));
    setIsIdAutogenerated(false);
    setOpenTriggerExamples(null);
    setRunData("");
  }

  useEffect(() => {
    let cancelled = false;

    async function load(): Promise<void> {
      setLoading(true);
      setError(null);
      try {
        const response = await listJobs(server, token);
        if (cancelled) return;

        setJobs(response.jobs);
        if (response.jobs.length === 0) {
          selectJob(response.jobs, "new");
          return;
        }

        const currentSelectedJobId = selectedJobIdRef.current;
        const nextSelectedJobId = currentSelectedJobId !== "new" && response.jobs.some((job) => job.id === currentSelectedJobId)
          ? currentSelectedJobId
          : response.jobs[0].id;
        selectJob(response.jobs, nextSelectedJobId);
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "Failed to load jobs.");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [server, token]);

  useEffect(() => {
    if (openTriggerExamples === null) {
      return;
    }

    function handlePointerDown(event: MouseEvent): void {
      if (!openTriggerExamplesRef.current?.contains(event.target as Node)) {
        setOpenTriggerExamples(null);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [openTriggerExamples]);

  useEffect(() => {
    if (!notice) {
      return;
    }

    const timeout = window.setTimeout(() => {
      setNotice((current) => (current === notice ? null : current));
    }, 15_000);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [notice]);

  useEffect(() => {
    if (!requestedJobId) {
      appliedRequestedJobIdRef.current = null;
      return;
    }

    if (appliedRequestedJobIdRef.current === requestedJobId || jobs.length === 0) {
      return;
    }

    if (!jobs.some((job) => job.id === requestedJobId)) {
      return;
    }

    const timer = window.setTimeout(() => {
      appliedRequestedJobIdRef.current = requestedJobId;
      selectedJobIdRef.current = requestedJobId;
      selectJob(jobs, requestedJobId);
      setError(null);
      setNotice(null);
    }, 0);

    return () => {
      window.clearTimeout(timer);
    };
  }, [jobs, requestedJobId]);

  function updateDraft(patch: Partial<JobDefinition>): void {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function updateTrigger(index: number, patch: Partial<JobCronTrigger>): void {
    setDraft((current) => ({
      ...current,
      triggers: current.triggers.map((trigger, triggerIndex) =>
        triggerIndex === index ? { ...trigger, ...patch } : trigger,
      ),
    }));
  }

  async function refreshJobs(message?: string, preferredJobId: string | "new" = selectedJobId): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const response = await listJobs(server, token);
      setJobs(response.jobs);
      selectJob(response.jobs, preferredJobId);
      if (message) {
        setNotice(message);
      }
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : "Failed to refresh jobs.");
    } finally {
      setLoading(false);
    }
  }

  function handleCreateNew(): void {
    selectJob(jobs, "new");
    setError(null);
    setNotice(null);
  }

  async function handleSave(): Promise<void> {
    const normalizedDraft = normalizeJobDraft(draft);
    const validationError = validateJobDraft(normalizedDraft);
    if (validationError) {
      setError(validationError);
      setNotice(null);
      return;
    }

    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const saved = selectedJobId === "new"
        ? await createJob(server, token, normalizedDraft)
        : await updateJob(server, token, normalizedDraft.id, normalizedDraft);
      await refreshJobs(selectedJobId === "new" ? "Job created." : "Job saved.", saved.id);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Failed to save job.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(): Promise<void> {
    if (selectedJobId === "new") {
      handleCreateNew();
      return;
    }

    if (!window.confirm(`Delete job ${draft.name || draft.id}?`)) {
      return;
    }

    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await deleteJob(server, token, draft.id);
      await refreshJobs("Job deleted.", "new");
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Failed to delete job.");
    } finally {
      setSaving(false);
    }
  }

  async function handleRun(): Promise<void> {
    if (selectedJobId === "new") {
      setError("Save the job before running it.");
      setNotice(null);
      return;
    }

    if (isDraftDirty) {
      setError("Save job changes before running it.");
      setNotice(null);
      return;
    }

    setRunning(true);
    setError(null);
    setNotice(null);
    try {
      const result = await runJob(server, token, draft.id, runData === "" ? undefined : runData);
      setNotice(result.created_new_session
        ? `Run started in new session ${result.session_id}.`
        : `Run started in session ${result.session_id}.`);
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Failed to run job.");
    } finally {
      setRunning(false);
    }
  }

  const selectedSessionValue = draft.persistent_session_id ?? "";

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-[radial-gradient(circle_at_top_left,_color-mix(in_oklch,var(--accent)_55%,transparent),transparent_35%),linear-gradient(180deg,color-mix(in_oklch,var(--background)_96%,var(--muted))_0%,var(--background)_100%)]">
      <div className="border-b border-border/80 px-5 py-4 sm:px-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-border/80 bg-background/80 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground backdrop-blur">
              <Settings2 className="h-3.5 w-3.5" />
              Settings
            </div>
            <h1 className="mt-3 text-2xl font-semibold tracking-tight">Jobs</h1>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
              Manage prompts, cron triggers, and reusable attended sessions for automated agent runs.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void refreshJobs("Jobs refreshed.")}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-60"
              disabled={loading}
            >
              <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
              Refresh
            </button>
            <button
              type="button"
              onClick={handleCreateNew}
              className="inline-flex items-center gap-2 rounded-lg bg-foreground px-3 py-2 text-sm font-medium text-background hover:bg-foreground/90"
            >
              <Plus className="h-4 w-4" />
              New job
            </button>
          </div>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-0 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <aside className="border-b border-border/80 bg-background/65 lg:border-r lg:border-b-0">
          <div className="flex h-full min-h-0 flex-col">
            <div className="border-b border-border/70 px-5 py-3 text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
              Saved Jobs
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {loading ? (
                <div className="flex items-center gap-2 rounded-xl border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading jobs...
                </div>
              ) : jobs.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-border bg-background/80 px-4 py-6 text-sm text-muted-foreground">
                  No jobs yet. Create one to store prompts and optional cron schedules in jobs.yaml.
                </div>
              ) : (
                <div className="space-y-2">
                  {jobs.map((job) => {
                    const selected = selectedJobId === job.id;
                    return (
                      <button
                        key={job.id}
                        type="button"
                        onClick={() => {
                          selectJob(jobs, job.id);
                          setError(null);
                          setNotice(null);
                        }}
                        className={cn(
                          "w-full rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                          selected
                            ? "bg-accent text-accent-foreground"
                            : "text-foreground/80 hover:bg-muted",
                        )}
                      >
                        <div className="flex items-start justify-between gap-3 px-3 pt-2 pb-1 text-left">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold">{job.name}</div>
                            <div className={cn(
                              "mt-0.5 truncate font-mono text-xs",
                              selected ? "text-accent-foreground/70" : "text-foreground/70",
                            )}>
                              {job.id}
                            </div>
                          </div>
                          {!job.enabled && (
                            <span className={cn(
                              "shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium flex items-center gap-1",
                              selected ? "bg-amber-900/20 text-amber-700" : "bg-amber-100 text-amber-700",
                            )}>
                              <Pause className="h-3 w-3" />
                              Paused
                            </span>
                          )}
                        </div>
                        <div className={cn(
                          "px-3 pb-2 text-xs flex items-center justify-between gap-3",
                          selected ? "text-accent-foreground/70" : "text-foreground/70",
                        )}>
                          <span>{summarizeJob(job)}</span>
                          {job.unattended && (
                            <button
                              type="button"
                              title="Unattended sessions cannot escalate tool calls"
                              className={cn(
                                "rounded-full p-1",
                                selected ? "hover:bg-accent-foreground/10" : "hover:bg-muted",
                              )}
                            >
                              <Bot className={cn("h-4 w-4", selected ? "text-accent-foreground" : "text-emerald-700")} />
                            </button>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </aside>

        <section className="min-h-0 overflow-y-auto px-5 py-5 sm:px-6">
          <div className="mx-auto flex max-w-4xl flex-col gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-3xl border border-border bg-background/88 px-5 py-4 shadow-sm">
              <p className="text-sm text-muted-foreground">
                {selectedJobId === "new" ? "New job" : `Editing ${draft.id || draft.name || "job"}`}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                {notice && !isDraftDirty ? <p className="text-sm text-emerald-700">{notice}</p> : null}
                <button
                  type="button"
                  onClick={() => void handleDelete()}
                  className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium text-destructive hover:bg-destructive/8 disabled:opacity-60"
                  disabled={saving || running}
                >
                  <Trash2 className="h-4 w-4" />
                  {selectedJobId === "new" ? "Clear" : "Delete"}
                </button>
                <button
                  type="button"
                  onClick={() => void handleSave()}
                  className="inline-flex items-center gap-2 rounded-lg bg-foreground px-3 py-2 text-sm font-medium text-background hover:bg-foreground/90 disabled:opacity-60 disabled:hover:bg-foreground"
                  disabled={saving || running || loading || draftValidationError !== null || !isDraftDirty}
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Save
                </button>
              </div>
            </div>

            <div className="rounded-3xl border border-border bg-background/88 p-5 shadow-sm">
              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-1.5">
                  <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Name</span>
                  <input
                    value={draft.name}
                    onChange={(event) => {
                      const name = event.target.value;
                      const nextPatch: Partial<JobDefinition> = { name };

                      if (selectedJobId === "new" && isIdAutogenerated) {
                        nextPatch.id = toKebabCaseId(name);
                      }

                      updateDraft(nextPatch);
                    }}
                    placeholder="Nightly inbox review"
                    disabled={saving || running}
                    className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                  />
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Job ID</span>
                  <input
                    value={draft.id}
                    onChange={(event) => {
                      const id = event.target.value;
                      setIsIdAutogenerated(selectedJobId === "new" && !id.trim());
                      updateDraft({ id });
                    }}
                    placeholder="nightly-inbox-review"
                    disabled={saving || running || selectedJobId !== "new"}
                    className="w-full rounded-xl border border-border bg-background px-3 py-2.5 font-mono text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                  />
                </label>
              </div>

              <div className="mt-4 space-y-3">
                <div className="space-y-3 rounded-2xl border border-border bg-muted/35 p-4">
                  <label className="flex items-start gap-3 rounded-xl border border-border/70 bg-background px-3 py-3">
                    <input
                      type="checkbox"
                      checked={draft.enabled}
                      onChange={(event) => updateDraft({ enabled: event.target.checked })}
                      disabled={saving || running}
                      className="mt-0.5 h-4 w-4 rounded border-border"
                    />
                    <span>
                      <span className="block text-sm font-medium">Enabled</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">Paused jobs stay in jobs.yaml but never run from cron.</span>
                    </span>
                  </label>

                  <label className="flex items-start gap-3 rounded-xl border border-border/70 bg-background px-3 py-3">
                    <input
                      type="checkbox"
                      checked={draft.unattended}
                      onChange={(event) => {
                        const unattended = event.target.checked;
                        updateDraft({
                          unattended,
                          persistent_session_id: unattended ? null : draft.persistent_session_id,
                        });
                      }}
                      disabled={saving || running}
                      className="mt-0.5 h-4 w-4 rounded border-border"
                    />
                    <span>
                      <span className="block text-sm font-medium">Run unattended</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">Tool calls will not be escalated to you.</span>
                    </span>
                  </label>
                </div>

                <div className="space-y-1.5 rounded-2xl border border-border bg-muted/35 p-4">
                  <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Persistent Session</span>
                  <input
                    list="jobs-session-options"
                    value={selectedSessionValue}
                    onChange={(event) => updateDraft({
                      persistent_session_id: event.target.value || null,
                      unattended: event.target.value ? false : draft.unattended,
                    })}
                    placeholder={draft.unattended ? "Can't be used in unattended mode" : undefined}
                    disabled={saving || running || draft.unattended}
                    className="w-full rounded-xl border border-border bg-background px-3 py-2.5 font-mono text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                  />
                  <datalist id="jobs-session-options">
                    {selectableSessions.map((session) => (
                      <option key={session.session_id} value={session.session_id} label={formatSessionOption(session)} />
                    ))}
                  </datalist>
                  <p className="text-xs text-muted-foreground">Reuse an existing session instead of creating a new one on every job invocation.</p>
                </div>
              </div>

              <div className="mt-4">
                <label className="space-y-1.5">
                  <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Prompt</span>
                  <textarea
                    value={draft.prompt}
                    onChange={(event) => updateDraft({ prompt: event.target.value })}
                    placeholder="Summarize new tasks, triage urgent items, then propose next actions."
                    disabled={saving || running}
                    rows={9}
                    className="w-full rounded-2xl border border-border bg-background px-3 py-3 text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                  />
                </label>
              </div>
            </div>

            <div className="rounded-3xl border border-border bg-background/88 p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Cron Triggers</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Leave empty for on-demand jobs.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setDraft((current) => ({
                    ...current,
                    triggers: [...current.triggers, createEmptyTrigger(detectedTimeZone)],
                  }))}
                  className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-muted"
                  disabled={saving || running}
                >
                  <Plus className="h-4 w-4" />
                  Add trigger
                </button>
              </div>

              {draft.triggers.length === 0 ? (
                <div className="mt-4 rounded-2xl border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
                  No cron triggers configured.
                </div>
              ) : (
                <div className="mt-4 space-y-3">
                  {draft.triggers.map((trigger, index) => (
                    (() => {
                      const cronDescription = describeCronExpression(trigger.expression);
                      return (
                    <div
                      key={`${index}-${selectedJobId}`}
                      className="grid gap-3 rounded-2xl border border-border bg-muted/35 p-4 md:grid-cols-[minmax(0,1fr)_14rem_auto]"
                    >
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Expression</span>
                        </div>
                        <div
                          ref={openTriggerExamples === index ? openTriggerExamplesRef : null}
                          className="relative"
                        >
                          <input
                            value={trigger.expression}
                            onChange={(event) => {
                              updateTrigger(index, { expression: event.target.value });
                              setOpenTriggerExamples(null);
                            }}
                            onFocus={() => setOpenTriggerExamples(index)}
                            onKeyDown={(event) => {
                              if (event.key === "Escape") {
                                setOpenTriggerExamples(null);
                              }
                            }}
                            role="combobox"
                            aria-expanded={openTriggerExamples === index}
                            aria-controls={`jobs-trigger-examples-${index}`}
                            disabled={saving || running}
                            className="w-full rounded-xl border border-border bg-background px-3 py-2.5 font-mono text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                          />
                          {openTriggerExamples === index ? (
                            <div
                              id={`jobs-trigger-examples-${index}`}
                              role="listbox"
                              className="absolute z-20 mt-2 max-h-72 w-full overflow-y-auto rounded-2xl border border-border bg-background p-2 shadow-xl"
                            >
                              <div className="space-y-1">
                                {cronExamples.map((example) => (
                                  <button
                                    key={example.expression}
                                    type="button"
                                    role="option"
                                    aria-selected={example.expression === trigger.expression.trim()}
                                    onClick={() => {
                                      updateTrigger(index, { expression: example.expression });
                                      setOpenTriggerExamples(null);
                                    }}
                                    className="w-full rounded-xl px-3 py-2 text-left transition-colors hover:bg-muted"
                                  >
                                    <div className="font-mono text-sm text-foreground">{example.expression}</div>
                                    <div className="mt-0.5 text-xs text-muted-foreground">{example.description}</div>
                                  </button>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      </div>
                      <label className="space-y-1.5">
                        <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Time Zone</span>
                        <select
                          value={trigger.timezone ?? detectedTimeZone}
                          onChange={(event) => updateTrigger(index, { timezone: event.target.value || null })}
                          disabled={saving || running}
                          className="w-full rounded-xl border border-border bg-background px-3 py-2.5 font-mono text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {timeZoneOptions.map((timeZone) => (
                            <option key={timeZone} value={timeZone}>
                              {timeZone}
                            </option>
                          ))}
                        </select>
                      </label>
                      <div className="flex items-end md:self-end">
                        <button
                          type="button"
                          onClick={() => setDraft((current) => ({
                            ...current,
                            triggers: current.triggers.filter((_, triggerIndex) => triggerIndex !== index),
                          }))}
                          onMouseDown={() => setOpenTriggerExamples((current) => {
                            if (current === null) return null;
                            if (current === index) return null;
                            return current > index ? current - 1 : current;
                          })}
                          className="inline-flex h-[46px] items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium text-destructive hover:bg-destructive/8"
                          disabled={saving || running}
                        >
                          <Trash2 className="h-4 w-4" />
                          Remove
                        </button>
                      </div>
                      {cronDescription ? (
                        <p
                          className={cn(
                            "text-xs md:col-span-2",
                            cronDescription.invalid
                              ? "text-destructive"
                              : "text-muted-foreground",
                          )}
                        >
                          {cronDescription.text}
                        </p>
                      ) : null}
                    </div>
                      );
                    })()
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-3xl border border-border bg-background/88 p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Run Job</h2>
                </div>
                <button
                  type="button"
                  onClick={() => void handleRun()}
                  className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-background"
                  disabled={saving || running || selectedJobId === "new" || isDraftDirty}
                >
                  {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  Run now
                </button>
              </div>
              <label className="mt-4 block space-y-1.5">
                <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Input (Optional)</span>
                <textarea
                  value={runData}
                  onChange={(event) => setRunData(event.target.value)}
                  disabled={saving || running}
                  rows={5}
                  className="w-full rounded-2xl border border-border bg-background px-3 py-3 font-mono text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                />
              </label>
            </div>

            <div className="rounded-3xl border border-border bg-background/88 p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Previous Invocations</h2>
                  <p className="mt-1 text-sm text-muted-foreground">Select an invocation to open its session.</p>
                </div>
              </div>

              {selectedJobId === "new" ? (
                <div className="mt-4 rounded-2xl border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
                  Save this job to view invocation history.
                </div>
              ) : selectedJobInvocations.length === 0 ? (
                <div className="mt-4 rounded-2xl border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
                  No invocations yet. Refresh sessions to load newly completed runs.
                </div>
              ) : (
                <div className="mt-4 space-y-2">
                  {selectedJobInvocations.map((session) => {
                    const latestJobRun = session.latest_job_run;
                    if (!latestJobRun) {
                      return null;
                    }

                    return (
                      <button
                        key={session.session_id}
                        type="button"
                        onClick={() => onSessionActivated(session)}
                        className="w-full rounded-2xl border border-border bg-background/90 px-4 py-3 text-left transition-colors hover:bg-muted"
                        disabled={saving || running}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-foreground">{session.title?.trim() || session.session_id}</div>
                            <div className="mt-1 truncate font-mono text-xs text-muted-foreground">{session.session_id}</div>
                          </div>
                          <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                            {formatTriggerKindLabel(latestJobRun.trigger_kind)}
                          </span>
                        </div>
                        <div className="mt-2 text-xs text-muted-foreground">
                          Ran at {formatInvocationTimestamp(latestJobRun.triggered_at)}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            {visibleError ? (
              <div className="rounded-2xl border border-border bg-background/88 px-4 py-3 text-sm shadow-sm">
                <p className="text-destructive">{visibleError}</p>
              </div>
            ) : null}

          </div>
        </section>
      </div>
    </div>
  );
}
