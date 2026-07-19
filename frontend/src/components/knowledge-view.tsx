"use client";

import { ChevronRight, Download, File, FileText, Folder, Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { useAppShell } from "@/components/app-shell-context";
import { MarkdownContent } from "@/components/markdown-content";
import {
  browseKnowledge,
  fetchKnowledgeText,
  knowledgeRawUrl,
  type KnowledgeBrowseResult,
  type KnowledgeEntry,
  type KnowledgeFileInfo,
} from "@/lib/api";
import { fencedCodeBlock, languageFromFilePath } from "@/lib/sandbox-read";
import { cn } from "@/lib/utils";

const MAX_TEXT_PREVIEW_BYTES = 1024 * 1024;

const TEXT_MIMES = new Set([
  "application/json",
  "application/xml",
  "application/yaml",
  "application/toml",
  "application/x-sh",
  "application/javascript",
]);

function isMarkdown(name: string): boolean {
  return /\.(md|markdown)$/i.test(name);
}

function isTextFile(file: KnowledgeFileInfo): boolean {
  if (file.mime.startsWith("text/") || TEXT_MIMES.has(file.mime)) return true;
  return languageFromFilePath(file.name) !== "text" || isMarkdown(file.name);
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function browseHref(path: string): string {
  return path ? `/knowledge?path=${encodeURIComponent(path)}` : "/knowledge";
}

function Breadcrumb({ path, rootLabel }: { path: string; rootLabel: string }) {
  const segments = path ? path.split("/") : [];
  return (
    <nav aria-label={rootLabel} className="flex min-w-0 flex-wrap items-center gap-1 text-sm">
      <Link
        href={browseHref("")}
        className="shrink-0 rounded-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {rootLabel}
      </Link>
      {segments.map((segment, index) => {
        const segmentPath = segments.slice(0, index + 1).join("/");
        const last = index === segments.length - 1;
        return (
          <span key={segmentPath} className="flex min-w-0 items-center gap-1">
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
            {last ? (
              <span className="truncate font-medium text-foreground">{segment}</span>
            ) : (
              <Link
                href={browseHref(segmentPath)}
                className="truncate rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {segment}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}

function EntryRow({ path, entry }: { path: string; entry: KnowledgeEntry }) {
  const entryPath = path ? `${path}/${entry.name}` : entry.name;
  const Icon = entry.type === "dir" ? Folder : isMarkdown(entry.name) ? FileText : File;
  return (
    <Link
      href={browseHref(entryPath)}
      className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Icon
        className={cn(
          "h-4 w-4 shrink-0",
          entry.type === "dir" ? "text-accent-foreground/70" : "text-muted-foreground",
        )}
      />
      <span className="min-w-0 flex-1 truncate">{entry.name}</span>
      {entry.size != null ? (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{formatSize(entry.size)}</span>
      ) : null}
    </Link>
  );
}

function FileContent({
  server,
  file,
  text,
  noPreviewLabel,
}: {
  server: string;
  file: KnowledgeFileInfo;
  text: string | null;
  noPreviewLabel: string;
}) {
  if (file.mime.startsWith("image/")) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={knowledgeRawUrl(server, file.path)}
        alt={file.name}
        className="max-w-full rounded-lg border border-border"
      />
    );
  }
  if (text != null) {
    if (isMarkdown(file.name)) {
      return <MarkdownContent content={text} />;
    }
    return <MarkdownContent content={fencedCodeBlock(languageFromFilePath(file.name), text)} />;
  }
  return <p className="text-sm text-muted-foreground">{noPreviewLabel}</p>;
}

export function KnowledgeView() {
  const t = useTranslations("knowledge");
  const tApp = useTranslations("app");
  const { server } = useAppShell();
  const searchParams = useSearchParams();
  const path = (searchParams.get("path") ?? "").replace(/^\/+|\/+$/g, "");

  const [result, setResult] = useState<KnowledgeBrowseResult | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = `${t("title")} • ${tApp("name")}`;
  }, [t, tApp]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      setText(null);
      try {
        const browsed = await browseKnowledge(server, path);
        if (cancelled) return;
        setResult(browsed);
        if (browsed.type === "file" && isTextFile(browsed) && browsed.size <= MAX_TEXT_PREVIEW_BYTES) {
          const content = await fetchKnowledgeText(server, browsed.path);
          if (!cancelled) setText(content);
        }
      } catch (browseError) {
        if (!cancelled) {
          setResult(null);
          setError(browseError instanceof Error ? browseError.message : t("error"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [server, path, t]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-5 py-5 sm:px-6">
        <div className="flex items-center justify-between gap-3 pb-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
            <div className="mt-2">
              <Breadcrumb path={path} rootLabel={t("root")} />
            </div>
          </div>
          {result?.type === "file" ? (
            <a
              href={knowledgeRawUrl(server, result.path, { download: true })}
              title={t("download")}
              aria-label={t("download")}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Download className="h-4 w-4" />
            </a>
          ) : null}
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("loading")}
          </div>
        ) : error ? (
          <p className="py-8 text-sm text-destructive">{error}</p>
        ) : result?.type === "dir" ? (
          result.entries.length === 0 ? (
            <p className="py-8 text-sm text-muted-foreground">{t("empty")}</p>
          ) : (
            <div className="flex flex-col gap-0.5 rounded-lg border border-border p-1.5">
              {result.entries.map((entry) => (
                <EntryRow key={entry.name} path={result.path} entry={entry} />
              ))}
            </div>
          )
        ) : result?.type === "file" ? (
          <FileContent server={server} file={result} text={text} noPreviewLabel={t("noPreview")} />
        ) : null}
      </div>
    </div>
  );
}
