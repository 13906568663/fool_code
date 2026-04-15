import { useEffect, useRef, useState } from "react";
import { prepare, layout } from "@chenglou/pretext";
import type { DisplayMessage } from "../types";

const FONT = "14px ui-monospace, monospace";
const MAX_WIDTH = 680;
const LINE_HEIGHT = 22;

interface DescendState {
  active: boolean;
  x: number;
  y: number;
  lineCount: number;
}

const INACTIVE: DescendState = { active: false, x: 0, y: 0, lineCount: 0 };

export function useStreamingDescend(
  containerRef: React.RefObject<HTMLDivElement | null>,
  messages: DisplayMessage[],
): DescendState {
  const [state, setState] = useState<DescendState>(INACTIVE);
  const prevLineRef = useRef(0);

  const lastMsg = messages[messages.length - 1];
  const isStreaming = lastMsg?.streaming && lastMsg.role === "assistant";
  const content = isStreaming ? lastMsg.content : "";

  useEffect(() => {
    if (!isStreaming || !content) {
      setState(INACTIVE);
      prevLineRef.current = 0;
      return;
    }

    const container = containerRef.current;
    if (!container) return;

    let lineCount: number;
    try {
      const prepared = prepare(content, FONT);
      const result = layout(prepared, MAX_WIDTH, LINE_HEIGHT);
      lineCount = result.lineCount;
    } catch {
      lineCount = Math.ceil(content.length / 80);
    }

    if (lineCount <= prevLineRef.current) {
      prevLineRef.current = lineCount;
      return;
    }
    prevLineRef.current = lineCount;

    const containerRect = container.getBoundingClientRect();
    const scrollEl = container.querySelector('[data-virtuoso-scroller="true"]') as HTMLElement | null;
    const scrollHeight = scrollEl?.scrollHeight ?? containerRect.height;
    const scrollTop = scrollEl?.scrollTop ?? 0;

    const msgBottomEstimate = scrollHeight;
    const relativeY = Math.min(
      msgBottomEstimate - scrollTop - 80,
      containerRect.height - 100,
    );

    const x = containerRect.width - 100 - (lineCount % 2 === 0 ? 10 : 0);

    setState({
      active: true,
      x: Math.max(40, x),
      y: Math.max(40, relativeY),
      lineCount,
    });
  }, [isStreaming, content, containerRef]);

  return state;
}
