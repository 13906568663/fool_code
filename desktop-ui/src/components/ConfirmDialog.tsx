import { useEffect, useRef, useCallback } from "react";
import { AlertTriangle, Trash2, Info } from "lucide-react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "danger" | "warning" | "default";
  onConfirm: () => void;
  onCancel: () => void;
}

const VARIANT_CFG = {
  danger: {
    icon: Trash2,
    iconBg: "bg-red-50",
    iconColor: "text-red-500",
    btn: "bg-red-600 hover:bg-red-700 focus:ring-red-200",
  },
  warning: {
    icon: AlertTriangle,
    iconBg: "bg-amber-50",
    iconColor: "text-amber-500",
    btn: "bg-amber-600 hover:bg-amber-700 focus:ring-amber-200",
  },
  default: {
    icon: Info,
    iconBg: "bg-blue-50",
    iconColor: "text-blue-500",
    btn: "bg-blue-600 hover:bg-blue-700 focus:ring-blue-200",
  },
} as const;

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmText = "确定",
  cancelText = "取消",
  variant = "default",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  const cfg = VARIANT_CFG[variant];
  const Icon = cfg.icon;

  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => confirmRef.current?.focus());
    }
  }, [open]);

  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (!open) return;
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      } else if (e.key === "Enter") {
        e.preventDefault();
        onConfirm();
      }
    },
    [open, onCancel, onConfirm],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-[120] bg-black/30 backdrop-blur-[2px]"
        onClick={onCancel}
      />

      <div className="fixed inset-0 z-[121] flex items-center justify-center p-4">
        <div
          className="w-full max-w-sm overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-[0_24px_64px_rgba(0,0,0,0.18)]"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="p-6">
            <div className="flex items-start gap-4">
              <div
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${cfg.iconBg}`}
              >
                <Icon size={20} className={cfg.iconColor} />
              </div>
              <div className="min-w-0 pt-0.5">
                <h3 className="text-[15px] font-semibold text-gray-900">
                  {title}
                </h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-gray-500">
                  {message}
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-gray-100 bg-gray-50/60 px-5 py-3.5">
            <button
              onClick={onCancel}
              className="rounded-lg border border-gray-200 bg-white px-4 py-[7px] text-[13px] font-medium text-gray-600 transition hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-200"
            >
              {cancelText}
            </button>
            <button
              ref={confirmRef}
              onClick={onConfirm}
              className={`rounded-lg px-4 py-[7px] text-[13px] font-medium text-white transition focus:outline-none focus:ring-2 ${cfg.btn}`}
            >
              {confirmText}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
