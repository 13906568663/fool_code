import { useEffect, useMemo, useState } from "react";
import { prepare, layout } from "@chenglou/pretext";

interface SpeechBubbleProps {
  text: string;
  color: string;
  onRight: boolean;
}

const FONT = "13px system-ui, -apple-system, sans-serif";
const MAX_WIDTH = 180;
const LINE_HEIGHT = 18;
const PADDING_X = 12;
const PADDING_Y = 8;
const BORDER_RADIUS = 12;

export default function SpeechBubble({ text, color, onRight }: SpeechBubbleProps) {
  const [visible, setVisible] = useState(false);
  const [displayText, setDisplayText] = useState("");

  const { height, lineCount } = useMemo(() => {
    if (!text) return { height: 0, lineCount: 0 };
    try {
      const prepared = prepare(text, FONT);
      return layout(prepared, MAX_WIDTH - PADDING_X * 2, LINE_HEIGHT);
    } catch {
      const cpl = Math.floor((MAX_WIDTH - PADDING_X * 2) / 7);
      const lines = Math.ceil(text.length / cpl);
      return { height: lines * LINE_HEIGHT, lineCount: lines };
    }
  }, [text]);

  const totalHeight = height + PADDING_Y * 2;
  const bubbleWidth = Math.min(
    MAX_WIDTH,
    lineCount <= 1 ? text.length * 7.5 + PADDING_X * 2 + 4 : MAX_WIDTH,
  );

  useEffect(() => {
    if (!text) {
      setVisible(false);
      setDisplayText("");
      return;
    }
    setVisible(true);
    setDisplayText("");
    let i = 0;
    const timer = setInterval(() => {
      i++;
      if (i >= text.length) {
        setDisplayText(text);
        clearInterval(timer);
      } else {
        setDisplayText(text.slice(0, i));
      }
    }, 30);
    return () => clearInterval(timer);
  }, [text]);

  if (!text || !visible) return null;

  return (
    <div
      style={{
        position: "absolute",
        bottom: "100%",
        [onRight ? "right" : "left"]: 0,
        marginBottom: 4,
        opacity: visible ? 1 : 0,
        transition: "opacity 0.3s ease",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          position: "relative",
          width: bubbleWidth,
          minHeight: totalHeight,
          padding: `${PADDING_Y}px ${PADDING_X}px`,
          backgroundColor: "white",
          border: `1.5px solid ${color}40`,
          borderRadius: BORDER_RADIUS,
          boxShadow: `0 4px 16px ${color}15, 0 2px 4px rgba(0,0,0,0.05)`,
          fontSize: "13px",
          lineHeight: `${LINE_HEIGHT}px`,
          color: "#475569",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {displayText}
        <div
          style={{
            position: "absolute",
            bottom: -6,
            [onRight ? "right" : "left"]: 16,
            width: 10,
            height: 10,
            backgroundColor: "white",
            border: `1.5px solid ${color}40`,
            borderTop: "none",
            borderLeft: onRight ? "none" : undefined,
            borderRight: onRight ? undefined : "none",
            transform: "rotate(45deg)",
          }}
        />
      </div>
    </div>
  );
}
