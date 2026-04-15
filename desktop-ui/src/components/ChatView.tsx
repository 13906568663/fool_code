import { useEffect, useRef } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { Settings } from "lucide-react";
import type { Artifact, DisplayMessage, TodoItem } from "../types";
import MessageBubble from "./MessageBubble";
import { usePretextHeights } from "../hooks/usePretextHeight";
import RoamingPet from "../buddy/RoamingPet";

interface ChatViewProps {
  messages: DisplayMessage[];
  configured?: boolean;
  onOpenSettings?: () => void;
  onOpenArtifact?: (artifact: Artifact) => void;
  todos?: TodoItem[];
  planStatus?: string;
  planReady?: boolean;
  planSlug?: string | null;
  onExecutePlan?: () => void;
  onDiscardPlan?: () => void;
  onRefinePlan?: () => void;
}

function WelcomeScreen({
  configured,
  onOpenSettings,
}: {
  configured: boolean;
  onOpenSettings?: () => void;
}) {
  return (
    <div className="mx-auto flex w-full max-w-[780px] flex-col items-center justify-center rounded-[32px] border border-[#E7ECF3] bg-[linear-gradient(180deg,#FFFFFF,#FCFDFF)] px-8 py-12 text-center shadow-[0_18px_52px_rgba(31,42,68,0.05)]">
      <div className="rounded-full border border-[#E7ECF3] bg-[#FCFDFF] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#4C84FF]">
        Fool Code
      </div>
      <h2 className="mt-5 text-[32px] font-semibold tracking-tight text-slate-800">
        欢迎使用 Fool Code
      </h2>
      <p className="mt-3 max-w-[540px] text-sm leading-7 text-slate-500 sm:text-[15px]">
        在下方输入问题、任务或拖入文件，我们会把上下文整理好，再继续把事情往前推进。
      </p>
      <p className="mt-2 text-xs text-slate-400">
        支持多行输入、拖拽文件、Enter 发送、Shift + Enter 换行。
      </p>

      {!configured && (
        <div className="mt-8 w-full max-w-[420px] rounded-[24px] border border-amber-200 bg-amber-50 px-5 py-4 text-left shadow-[0_10px_28px_rgba(217,119,6,0.08)]">
          <div className="text-sm font-semibold text-amber-800">
            尚未配置 AI 模型
          </div>
          <div className="mt-1 text-xs leading-6 text-amber-700">
            先补齐提供商、模型和 API Key，聊天、工具调用和会话能力就能完整工作了。
          </div>
          <button
            onClick={onOpenSettings}
            className="mt-4 inline-flex items-center gap-2 rounded-full bg-amber-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-amber-700"
          >
            <Settings size={14} />
            前往设置
          </button>
        </div>
      )}
    </div>
  );
}

export default function ChatView({
  messages,
  configured = true,
  onOpenSettings,
  onOpenArtifact,
  todos = [],
  planStatus,
  planReady,
  planSlug,
  onExecutePlan,
  onDiscardPlan,
  onRefinePlan,
}: ChatViewProps) {
  const virtuosoRef = useRef<VirtuosoHandle>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const { defaultHeight } = usePretextHeights(messages);
  const firstId = messages[0]?.id;

  useEffect(() => {
    if (messages.length > 0) {
      requestAnimationFrame(() => {
        virtuosoRef.current?.scrollToIndex({
          index: messages.length - 1,
          align: "end",
          behavior: "auto",
        });
      });
    }
  }, [messages.length, firstId]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center overflow-y-auto px-4 pb-4 pt-5 sm:px-6 sm:pb-6">
        <WelcomeScreen
          configured={configured}
          onOpenSettings={onOpenSettings}
        />
      </div>
    );
  }

  return (
    <div ref={chatContainerRef} className="flex-1 overflow-hidden" style={{ position: "relative" }}>
      <Virtuoso
        ref={virtuosoRef}
        style={{ height: "100%" }}
        data={messages}
        defaultItemHeight={defaultHeight}
        followOutput={(isAtBottom) => (isAtBottom ? "smooth" : false)}
        initialTopMostItemIndex={messages.length - 1}
        increaseViewportBy={{ top: 200, bottom: 200 }}
        itemContent={(_index, message) => (
          <div className="mx-auto w-full max-w-[1120px] px-4 pb-6 sm:px-6">
            <MessageBubble
              message={message}
              todos={message.isPlan ? todos : undefined}
              planStatus={message.isPlan ? planStatus : undefined}
              planReady={message.isPlan ? planReady : undefined}
              planSlug={message.isPlan ? planSlug : undefined}
              onExecutePlan={message.isPlan ? onExecutePlan : undefined}
              onDiscardPlan={message.isPlan ? onDiscardPlan : undefined}
              onRefinePlan={message.isPlan ? onRefinePlan : undefined}
              onOpenArtifact={onOpenArtifact}
            />
          </div>
        )}
      />
      <RoamingPet containerRef={chatContainerRef} messages={messages} />
    </div>
  );
}
