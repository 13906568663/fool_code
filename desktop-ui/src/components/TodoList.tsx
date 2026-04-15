import {
  Check,
  Circle,
  ChevronDown,
  ChevronRight,
  ListTodo,
  LoaderCircle,
} from "lucide-react";
import { useState } from "react";
import type { TodoItem } from "../types";

interface TodoListProps {
  todos: TodoItem[];
  mini?: boolean;
}

function StatusIcon({ status }: { status: TodoItem["status"] }) {
  switch (status) {
    case "completed":
      return (
        <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white">
          <Check size={12} strokeWidth={3} />
        </span>
      );
    case "in_progress":
      return (
        <LoaderCircle
          size={20}
          className="flex-shrink-0 animate-spin text-blue-500"
        />
      );
    default:
      return <Circle size={20} className="flex-shrink-0 text-slate-300" />;
  }
}

function MiniTodoList({ todos }: { todos: TodoItem[] }) {
  const completedCount = todos.filter((t) => t.status === "completed").length;
  const current = todos.find((t) => t.status === "in_progress");
  const allDone = completedCount === todos.length;
  const pct = todos.length > 0 ? Math.round((completedCount / todos.length) * 100) : 0;

  return (
    <div className="flex items-center gap-3 rounded-xl border border-slate-100 bg-slate-50/80 px-3 py-2">
      <div className="h-1 w-16 overflow-hidden rounded-full bg-slate-200">
        <div
          className="h-full rounded-full bg-blue-500 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs tabular-nums text-slate-400">
        {completedCount}/{todos.length}
      </span>
      {allDone ? (
        <span className="text-xs font-medium text-emerald-600">全部完成</span>
      ) : current ? (
        <span className="truncate text-xs text-slate-500">
          {current.content}
        </span>
      ) : null}
    </div>
  );
}

export default function TodoList({ todos, mini = false }: TodoListProps) {
  const [collapsed, setCollapsed] = useState(false);

  if (todos.length === 0) return null;

  if (mini) return <MiniTodoList todos={todos} />;

  const completedCount = todos.filter((t) => t.status === "completed").length;
  const allDone = completedCount === todos.length;
  const pct = todos.length > 0 ? Math.round((completedCount / todos.length) * 100) : 0;

  return (
    <div
      className={`rounded-2xl border shadow-[0_10px_24px_rgba(31,42,68,0.05)] ${
        allDone
          ? "border-emerald-200 bg-gradient-to-b from-emerald-50/40 to-white"
          : "border-[#E7ECF3] bg-white"
      }`}
    >
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center gap-2.5 px-4 py-3 text-left transition hover:bg-slate-50/50"
      >
        <ListTodo size={16} className="flex-shrink-0 text-slate-500" />
        <span className="flex-1 text-sm font-medium text-slate-700">
          任务进度
        </span>

        {/* Progress bar inline */}
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-20 overflow-hidden rounded-full bg-slate-100">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                allDone ? "bg-emerald-500" : "bg-blue-500"
              }`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs tabular-nums text-slate-400">
            {completedCount}/{todos.length}
          </span>
        </div>

        {allDone && (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-600">
            完成
          </span>
        )}

        <span className="text-slate-300">
          {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>

      {!collapsed && (
        <div className="border-t border-[#F0F3F8] px-4 py-2">
          <div className="divide-y divide-[#F0F3F8]">
            {todos.map((todo, idx) => (
              <div key={idx} className="flex items-start gap-2.5 py-1.5">
                <div className="mt-0.5">
                  <StatusIcon status={todo.status} />
                </div>
                <span
                  className={`min-w-0 flex-1 text-[14px] leading-6 ${
                    todo.status === "completed"
                      ? "text-slate-400 line-through"
                      : todo.status === "in_progress"
                        ? "font-medium text-slate-800"
                        : "text-slate-600"
                  }`}
                >
                  {todo.content}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
