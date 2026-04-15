import { useCallback, useEffect, useState } from "react";
import { Check, HelpCircle, SkipForward } from "lucide-react";
import type { AskUserQuestionItem } from "../types";

interface AskUserDialogProps {
  questions: AskUserQuestionItem[];
  onSubmit: (answers: Record<string, string>) => void | Promise<void>;
  onSkip: () => void | Promise<void>;
}

export default function AskUserDialog({
  questions,
  onSubmit,
  onSkip,
}: AskUserDialogProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  const allAnswered = questions.every((_, idx) => answers[String(idx)]);

  const selectOption = useCallback((questionIdx: number, label: string) => {
    setAnswers((prev) => ({ ...prev, [String(questionIdx)]: label }));
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!allAnswered || submitting) return;
    setSubmitting(true);
    try {
      await onSubmit(answers);
    } finally {
      setSubmitting(false);
    }
  }, [allAnswered, submitting, onSubmit, answers]);

  const handleSkip = useCallback(async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      await onSkip();
    } finally {
      setSubmitting(false);
    }
  }, [submitting, onSkip]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (submitting) return;
      if (e.key === "Enter" && allAnswered) {
        e.preventDefault();
        void handleSubmit();
      }
      if (e.key === "Escape") {
        e.preventDefault();
        void handleSkip();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleSubmit, handleSkip, allAnswered, submitting]);

  return (
    <>
      <div className="fixed inset-0 z-[200] bg-slate-950/35 backdrop-blur-sm" />
      <div className="fixed inset-0 z-[201] flex items-center justify-center p-4">
        <div className="w-full max-w-[720px] overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_28px_80px_rgba(15,23,42,0.22)]">
          <div className="border-b border-slate-200 bg-[linear-gradient(135deg,#eff6ff_0%,#ffffff_55%,#f8fafc_100%)] px-6 py-5">
            <div className="mb-1 inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-blue-700">
              <HelpCircle size={14} />
              AI 需要你的选择
            </div>
            <h3 className="mt-2 text-xl font-semibold tracking-tight text-slate-900">
              请回答以下问题
            </h3>
            <p className="mt-1 text-sm leading-6 text-slate-500">
              AI 在制定计划前需要了解你的偏好，请选择最符合你需求的选项。
            </p>
          </div>

          <div className="max-h-[60vh] space-y-5 overflow-y-auto px-6 py-5">
            {questions.map((q, qIdx) => (
              <div key={qIdx}>
                <div className="mb-3 flex items-start gap-2.5">
                  <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-700">
                    {qIdx + 1}
                  </span>
                  <p className="text-[15px] font-medium leading-6 text-slate-800">
                    {q.question}
                  </p>
                </div>

                <div className="ml-8 space-y-2">
                  {q.options.map((opt, oIdx) => {
                    const selected = answers[String(qIdx)] === opt.label;
                    return (
                      <button
                        key={oIdx}
                        type="button"
                        onClick={() => selectOption(qIdx, opt.label)}
                        className={`flex w-full items-start gap-3 rounded-2xl border px-4 py-3 text-left transition-all ${
                          selected
                            ? "border-blue-400 bg-blue-50/80 ring-2 ring-blue-200"
                            : "border-slate-200 bg-white hover:border-blue-300 hover:bg-blue-50/40"
                        }`}
                      >
                        <span
                          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-all ${
                            selected
                              ? "border-blue-500 bg-blue-500 text-white"
                              : "border-slate-300 bg-white"
                          }`}
                        >
                          {selected && <Check size={12} strokeWidth={3} />}
                        </span>
                        <div className="min-w-0 flex-1">
                          <span
                            className={`text-sm font-medium ${
                              selected ? "text-blue-800" : "text-slate-700"
                            }`}
                          >
                            {opt.label}
                          </span>
                          {opt.description && (
                            <p className="mt-0.5 text-xs leading-5 text-slate-500">
                              {opt.description}
                            </p>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50 px-6 py-4">
            <div className="text-xs text-slate-400">
              Enter 提交 · Esc 跳过
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void handleSkip()}
                disabled={submitting}
                className="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-600 transition hover:bg-slate-100 disabled:opacity-50"
              >
                <SkipForward size={14} />
                跳过，让 AI 自行决定
              </button>
              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={!allAnswered || submitting}
                className="inline-flex items-center gap-1.5 rounded-xl border border-blue-200 bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Check size={14} />
                确认选择
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
