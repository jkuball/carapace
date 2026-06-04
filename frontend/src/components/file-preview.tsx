"use client";

import { useEffect, useState } from "react";
import { Download, File as FileIcon } from "lucide-react";
import { fetchSentFile, sentFileUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/** Renders a persisted file: inline image preview for images, plus a name/size/download chip. */
export function FilePreview({
  fileId,
  name,
  mime,
  size,
  server,
  sessionId,
  className,
}: {
  fileId: string;
  name: string;
  mime?: string;
  size?: number;
  server?: string;
  sessionId?: string;
  className?: string;
}) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const isImage = (mime ?? "").startsWith("image/");
  const canFetch = server !== undefined && sessionId !== undefined;

  useEffect(() => {
    if (!isImage || !canFetch) return;
    let url: string | null = null;
    let cancelled = false;
    fetchSentFile(server, sessionId, fileId)
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setPreviewUrl(url);
      })
      .catch(() => {
        /* fall back to the download chip below */
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [isImage, canFetch, server, sessionId, fileId]);

  const downloadHref = canFetch
    ? sentFileUrl(server, sessionId, fileId, { download: true })
    : undefined;

  return (
    <div className={cn("rounded-md border border-border/40 bg-muted/25 p-2", className)}>
      {isImage && previewUrl && (
        <a href={previewUrl} target="_blank" rel="noreferrer" className="block">
          {/* eslint-disable-next-line @next/next/no-img-element -- blob: object URL, next/image can't optimize it */}
          <img
            src={previewUrl}
            alt={name}
            className="max-h-80 w-auto max-w-full rounded"
          />
        </a>
      )}
      <div className="mt-1.5 flex items-center gap-2 first:mt-0">
        <FileIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="truncate font-medium text-foreground/85">{name}</span>
        {size != null && (
          <span className="shrink-0 text-muted-foreground">{formatFileSize(size)}</span>
        )}
        {downloadHref && (
          <a
            href={downloadHref}
            download={name}
            className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium text-teal-600 hover:bg-teal-500/10 dark:text-teal-400"
          >
            <Download className="h-3 w-3" />
            Download
          </a>
        )}
      </div>
    </div>
  );
}
