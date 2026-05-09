"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Play, Plus, RefreshCw, Save, Settings2, Trash2 } from "lucide-react";
import { createJob, deleteJob, listJobs, runJob, updateJob } from "@/lib/api";
import type { JobCronTrigger, JobDefinition, SessionInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

interface JobsViewProps {
  server: string;
  token: string;
  sessions: SessionInfo[];
  onSessionActivated: (session: SessionInfo) => void;
}

const EMPTY_TRIGGER: JobCronTrigger = {
  type: "cron",
  expression: "",
  timezone: "UTC",
};

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

  return null;
}

function formatSessionOption(session: SessionInfo): string {
  const label = session.title?.trim();
  if (!label) return session.session_id;
  return `${label} (${session.session_id})`;
}

export function JobsView({ server, token, sessions, onSessionActivated }: JobsViewProps) {
  const [jobs, setJobs] = useState<JobDefinition[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | "new">("new");
  const [draft, setDraft] = useState<JobDefinition>(createEmptyJob);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const selectedJobIdRef = useRef<string | "new">("new");

  const selectableSessions = useMemo(
    () => sessions.filter((session) => !session.attributes.unattended && !session.attributes.archived),
    [sessions],
  );

  function selectJob(nextJobs: JobDefinition[], nextSelectedJobId: string | "new"): void {
    if (nextSelectedJobId === "new") {
      selectedJobIdRef.current = "new";
      setSelectedJobId("new");
      setDraft(createEmptyJob());
      return;
    }

    const selectedJob = nextJobs.find((job) => job.id === nextSelectedJobId) ?? nextJobs[0];
    if (!selectedJob) {
      selectedJobIdRef.current = "new";
      setSelectedJobId("new");
      setDraft(createEmptyJob());
      return;
    }

    selectedJobIdRef.current = selectedJob.id;
    setSelectedJobId(selectedJob.id);
    setDraft(structuredClone(selectedJob));
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

    setRunning(true);
    setError(null);
    setNotice(null);
    try {
      const result = await runJob(server, token, draft.id);
      onSessionActivated(result.session);
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
                          "w-full rounded-2xl border px-4 py-3 text-left transition-colors",
                          selected
                            ? "border-foreground/15 bg-foreground text-background"
                            : "border-border bg-background/90 hover:bg-muted",
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold">{job.name}</div>
                            <div className={cn(
                              "mt-1 truncate font-mono text-xs",
                              selected ? "text-background/70" : "text-muted-foreground",
                            )}>
                              {job.id}
                            </div>
                          </div>
                          <span className={cn(
                            "rounded-full px-2 py-0.5 text-[11px] font-medium",
                            job.enabled
                              ? (selected ? "bg-background/12 text-background" : "bg-emerald-100 text-emerald-800")
                              : (selected ? "bg-background/12 text-background/70" : "bg-muted text-muted-foreground"),
                          )}>
                            {job.enabled ? "Enabled" : "Disabled"}
                          </span>
                        </div>
                        <div className={cn(
                          "mt-3 flex items-center justify-between gap-3 text-xs",
                          selected ? "text-background/70" : "text-muted-foreground",
                        )}>
                          <span>{summarizeJob(job)}</span>
                          <span>{job.unattended ? "Unattended" : "Attended"}</span>
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
            <div className="rounded-3xl border border-border bg-background/88 p-5 shadow-sm">
              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-1.5">
                  <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Job ID</span>
                  <input
                    value={draft.id}
                    onChange={(event) => updateDraft({ id: event.target.value })}
                    placeholder="nightly-inbox-review"
                    disabled={saving || running || selectedJobId !== "new"}
                    className="w-full rounded-xl border border-border bg-background px-3 py-2.5 font-mono text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                  />
                </label>
                <label className="space-y-1.5">
                  <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Name</span>
                  <input
                    value={draft.name}
                    onChange={(event) => updateDraft({ name: event.target.value })}
                    placeholder="Nightly inbox review"
                    disabled={saving || running}
                    className="w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                  />
                </label>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
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
                      <span className="mt-0.5 block text-xs text-muted-foreground">Disabled jobs stay in jobs.yaml but never run from cron.</span>
                    </span>
                  </label>

                  <label className="flex items-start gap-3 rounded-xl border border-border/70 bg-background px-3 py-3">
                    <input
                      type="checkbox"
                      checked={draft.unattended}
                      onChange={(event) => updateDraft({ unattended: event.target.checked })}
                      disabled={saving || running || !!draft.persistent_session_id}
                      className="mt-0.5 h-4 w-4 rounded border-border"
                    />
                    <span>
                      <span className="block text-sm font-medium">Run unattended</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">Turn this off when reusing an attended persistent session.</span>
                    </span>
                  </label>

                  <label className="space-y-1.5">
                    <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Persistent Session</span>
                    <input
                      list="jobs-session-options"
                      value={selectedSessionValue}
                      onChange={(event) => updateDraft({
                        persistent_session_id: event.target.value || null,
                        unattended: event.target.value ? false : draft.unattended,
                      })}
                      placeholder="Optional attended session id"
                      disabled={saving || running}
                      className="w-full rounded-xl border border-border bg-background px-3 py-2.5 font-mono text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                    />
                    <datalist id="jobs-session-options">
                      {selectableSessions.map((session) => (
                        <option key={session.session_id} value={session.session_id} label={formatSessionOption(session)} />
                      ))}
                    </datalist>
                    <p className="text-xs text-muted-foreground">
                      Accepts manual input. Suggestions only include existing attended, non-archived sessions.
                    </p>
                  </label>
                </div>
              </div>
            </div>

            <div className="rounded-3xl border border-border bg-background/88 p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">Cron Triggers</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Leave empty for on-demand jobs. Time zones use IANA names like UTC or Europe/Berlin.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setDraft((current) => ({ ...current, triggers: [...current.triggers, { ...EMPTY_TRIGGER }] }))}
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
                    <div key={`${index}-${selectedJobId}`} className="grid gap-3 rounded-2xl border border-border bg-muted/35 p-4 md:grid-cols-[minmax(0,1fr)_14rem_auto]">
                      <label className="space-y-1.5">
                        <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Cron Expression</span>
                        <input
                          value={trigger.expression}
                          onChange={(event) => updateTrigger(index, { expression: event.target.value })}
                          placeholder="0 7 * * *"
                          disabled={saving || running}
                          className="w-full rounded-xl border border-border bg-background px-3 py-2.5 font-mono text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                        />
                      </label>
                      <label className="space-y-1.5">
                        <span className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Time Zone</span>
                        <input
                          value={trigger.timezone ?? ""}
                          onChange={(event) => updateTrigger(index, { timezone: event.target.value || null })}
                          placeholder="UTC"
                          disabled={saving || running}
                          className="w-full rounded-xl border border-border bg-background px-3 py-2.5 font-mono text-sm outline-none transition-colors focus:border-ring focus:ring-2 focus:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-60"
                        />
                      </label>
                      <div className="flex items-end">
                        <button
                          type="button"
                          onClick={() => setDraft((current) => ({
                            ...current,
                            triggers: current.triggers.filter((_, triggerIndex) => triggerIndex !== index),
                          }))}
                          className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium text-destructive hover:bg-destructive/8"
                          disabled={saving || running}
                        >
                          <Trash2 className="h-4 w-4" />
                          Remove
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {(error || notice) ? (
              <div className="rounded-2xl border border-border bg-background/88 px-4 py-3 text-sm shadow-sm">
                {error ? <p className="text-destructive">{error}</p> : null}
                {notice ? <p className="text-emerald-700">{notice}</p> : null}
              </div>
            ) : null}

            <div className="flex flex-wrap items-center justify-between gap-3 rounded-3xl border border-border bg-background/88 px-5 py-4 shadow-sm">
              <p className="text-sm text-muted-foreground">
                {selectedJobId === "new" ? "New job" : `Editing ${draft.id || draft.name || "job"}`}
              </p>
              <div className="flex flex-wrap items-center gap-2">
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
                  onClick={() => void handleRun()}
                  className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium hover:bg-muted disabled:opacity-60"
                  disabled={saving || running || selectedJobId === "new"}
                >
                  {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  Run now
                </button>
                <button
                  type="button"
                  onClick={() => void handleSave()}
                  className="inline-flex items-center gap-2 rounded-lg bg-foreground px-3 py-2 text-sm font-medium text-background hover:bg-foreground/90 disabled:opacity-60"
                  disabled={saving || running || loading}
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Save
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
