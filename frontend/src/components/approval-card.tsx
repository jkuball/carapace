import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { AlertCircle } from "lucide-react";
import type { ApprovalRequest } from "@/lib/types";
import { DenialNoteActions } from "./denial-note-actions";

interface ApprovalCardProps {
  request: ApprovalRequest;
  onRespond: (approved: boolean, message?: string) => void;
}

export function ApprovalCard({
  request,
  onRespond,
}: ApprovalCardProps) {
  const t = useTranslations("approval.general");
  const riskLabels: Record<NonNullable<ApprovalRequest["risk_level"]>, string> = {
    high: t("risk.high"),
    low: t("risk.low"),
    medium: t("risk.medium"),
  };

  return (
    <div
      className={cn(
        "my-2 rounded-lg border-2 border-warning/60 bg-warning/5 p-3 text-sm",
      )}
    >
      <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-warning-foreground/70">
        <AlertCircle className="h-3.5 w-3.5" />
        {t("title")}
      </div>

      <div className="space-y-1.5">
        <div>
          <span className="text-muted-foreground">{t("toolLabel")} </span>
          <span className="font-mono font-medium">{request.tool}</span>
        </div>
        {request.explanation && (
          <div>
            <span className="text-muted-foreground">{t("reasonLabel")} </span>
            <span>{request.explanation}</span>
          </div>
        )}
        {request.risk_level && (
          <div>
            <span className="text-muted-foreground">{t("riskLabel")} </span>
            <span
              className={cn(
                "font-medium",
                request.risk_level === "high" && "text-destructive",
                request.risk_level === "medium" && "text-warning-foreground",
                request.risk_level === "low" && "text-green-600 dark:text-green-400",
              )}
            >
              {riskLabels[request.risk_level]}
            </span>
          </div>
        )}
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors">
            {t("arguments")}
          </summary>
          <pre className="mt-1 rounded-md bg-muted p-2 font-mono overflow-x-auto whitespace-pre-wrap break-words">
            {JSON.stringify(request.args, null, 2)}
          </pre>
        </details>
      </div>

      <DenialNoteActions
        allowLabel={t("allow")}
        denyButtonClassName="border border-border text-foreground hover:bg-muted"
        notePlaceholder={t("denyPlaceholder")}
        onAllow={() => onRespond(true)}
        onDeny={(message) => onRespond(false, message)}
      />
    </div>
  );
}
