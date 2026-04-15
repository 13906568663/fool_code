import React, { useCallback, useEffect, useRef, useState, useMemo } from "react";
import { useCompanion } from "./useCompanion";
import { useRoaming, tickPhysics } from "./useRoaming";
import { scanPlatforms, type Platform } from "./platformScanner";
import { useStreamingDescend } from "./useStreamingDescend";
import SpriteRenderer, {
  ANIM_SPEEDS,
  FRAME_COUNTS,
  type CatAction,
  type SpriteHandle,
} from "./SpriteRenderer";
import SpeechBubble from "./SpeechBubble";
import HeartBurst from "./HeartBurst";
import { RARITY_COLORS } from "./types";
import type { DisplayMessage } from "../types";

// ---------------------------------------------------------------------------
// Context menu for pet actions
// ---------------------------------------------------------------------------

interface MenuItem {
  label: string;
  icon: string;
  action: () => void;
  hidden?: boolean;
}

function PetContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number;
  y: number;
  items: MenuItem[];
  onClose: () => void;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const visibleItems = useMemo(() => items.filter((i) => !i.hidden), [items]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const escHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("mousedown", handler);
    window.addEventListener("keydown", escHandler);
    return () => {
      window.removeEventListener("mousedown", handler);
      window.removeEventListener("keydown", escHandler);
    };
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      style={{
        position: "fixed",
        left: x,
        top: y,
        zIndex: 9999,
        minWidth: 140,
        background: "rgba(255, 255, 255, 0.96)",
        backdropFilter: "blur(12px)",
        borderRadius: 10,
        boxShadow: "0 4px 20px rgba(0,0,0,0.15), 0 1px 4px rgba(0,0,0,0.1)",
        border: "1px solid rgba(0,0,0,0.08)",
        padding: "4px 0",
        overflow: "hidden",
        pointerEvents: "auto",
      }}
    >
      {visibleItems.map((item, i) => (
        <div
          key={i}
          onClick={(e) => {
            e.stopPropagation();
            item.action();
            onClose();
          }}
          onMouseDown={(e) => e.stopPropagation()}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "7px 14px",
            fontSize: 13,
            cursor: "pointer",
            color: "#333",
            userSelect: "none",
            transition: "background 0.1s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLDivElement).style.background = "rgba(0,0,0,0.06)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLDivElement).style.background = "transparent";
          }}
        >
          <span style={{ fontSize: 15, width: 20, textAlign: "center" }}>{item.icon}</span>
          <span>{item.label}</span>
        </div>
      ))}
    </div>
  );
}

class BuddyErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  render() {
    if (this.state.hasError) return null;
    return this.props.children;
  }
}

interface RoamingPetProps {
  containerRef: React.RefObject<HTMLDivElement | null>;
  messages?: DisplayMessage[];
}

function RoamingPetInner({ containerRef, messages = [] }: RoamingPetProps) {
  const { companion, reaction, petting, sleeping, enabled, pet, toggle, triggerReaction, triggerGrab, triggerLand, wakeUp } =
    useCompanion();
  const isSpeaking = Boolean(reaction);

  const platformsRef = useRef<Platform[]>([]);
  const roamingRef = useRoaming(containerRef, isSpeaking, petting, sleeping, platformsRef);
  const descend = useStreamingDescend(containerRef, messages);
  const color = RARITY_COLORS[companion.rarity];

  const wrapperRef = useRef<HTMLDivElement>(null);
  const spriteWrapperRef = useRef<HTMLDivElement>(null);
  const spriteRef = useRef<SpriteHandle>(null);
  const rafRef = useRef<number>(0);
  const animStartRef = useRef(0);
  const lastActionRef = useRef<CatAction>("idle");
  const prevTimeRef = useRef(0);

  // Drag state
  const isDraggingRef = useRef(false);
  const dragOffsetRef = useRef({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);

  // Context menu state
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number } | null>(null);

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setCtxMenu({ x: e.clientX, y: e.clientY });
  }, []);

  const closeCtxMenu = useCallback(() => setCtxMenu(null), []);

  const menuItems = useMemo<MenuItem[]>(() => [
    { label: "撸猫", icon: "🐱", action: pet },
    {
      label: "打招呼", icon: "👋",
      action: () => triggerReaction("嗨嗨~ 喵！"),
    },
    {
      label: sleeping ? "叫醒" : "去睡觉", icon: sleeping ? "☀️" : "💤",
      action: () => {
        if (sleeping) {
          wakeUp();
          triggerReaction("(伸了个懒腰) 喵~");
        } else {
          triggerReaction("(打了个哈欠) 晚安…zzz");
          const r = roamingRef.current;
          r.action = "sleep";
          r.vx = 0;
        }
      },
    },
    { label: "隐藏宠物", icon: "👁️", action: toggle },
  ], [pet, triggerReaction, sleeping, wakeUp, toggle, roamingRef]);

  // Stable refs for values read inside rAF
  const pettingRef = useRef(petting);
  pettingRef.current = petting;
  const isSpeakingRef = useRef(isSpeaking);
  isSpeakingRef.current = isSpeaking;
  const descendRef = useRef(descend);
  descendRef.current = descend;
  const wasDizzyRef = useRef(false);

  // Drag: mousedown on sprite → follow cursor → release → fall
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const container = containerRef.current;
    if (!container) return;
    const cRect = container.getBoundingClientRect();
    const r = roamingRef.current;
    dragOffsetRef.current = {
      x: e.clientX - cRect.left - r.x,
      y: e.clientY - cRect.top - r.y,
    };
    isDraggingRef.current = true;
    setIsDragging(true);
    triggerGrab();

    const onMouseMove = (me: MouseEvent) => {
      const cR = containerRef.current?.getBoundingClientRect();
      if (!cR) return;
      const rr = roamingRef.current;
      rr.x = me.clientX - cR.left - dragOffsetRef.current.x;
      rr.y = me.clientY - cR.top - dragOffsetRef.current.y;
    };

    const onMouseUp = () => {
      isDraggingRef.current = false;
      setIsDragging(false);
      const rr = roamingRef.current;
      rr.onGround = false;
      rr.currentPlatform = null;
      rr.vy = 2;
      rr.vx = 0;
      rr.falling = true;
      rr.wasGrabbed = true;
      rr.grabReleaseY = rr.y;
      rr.dizzy = 0;
      rr.landing = 0;
      rr.action = "climb";
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }, [containerRef, roamingRef, triggerGrab]);

  // Debug: show detected platforms
  const [debug, setDebug] = useState(false);
  const [debugPlatforms, setDebugPlatforms] = useState<Platform[]>([]);

  // Platform scanning interval + scroll listener
  useEffect(() => {
    if (!enabled) return;
    const scan = () => {
      const el = containerRef.current;
      if (!el) return;
      platformsRef.current = scanPlatforms(el);
      if (debug) setDebugPlatforms([...platformsRef.current]);
    };
    scan();
    const id = setInterval(scan, 500);

    // Also listen for scroll inside the container (Virtuoso's scroller)
    const el = containerRef.current;
    const scroller =
      el?.querySelector('[data-virtuoso-scroller="true"]') ?? el;
    const onScroll = () => scan();
    scroller?.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      clearInterval(id);
      scroller?.removeEventListener("scroll", onScroll);
    };
  }, [enabled, containerRef, debug]);

  // --- Unified rAF loop ---
  const loop = useCallback(
    (now: number) => {
      const r = roamingRef.current;
      const wrapper = wrapperRef.current;
      const spriteWrapper = spriteWrapperRef.current;
      const sprite = spriteRef.current;

      if (!wrapper || !sprite || !sprite.ready || !spriteWrapper) {
        rafRef.current = requestAnimationFrame(loop);
        return;
      }

      // Delta time (capped to avoid huge jumps on tab switch)
      const dt = prevTimeRef.current ? Math.min(now - prevTimeRef.current, 50) : 16;
      prevTimeRef.current = now;

      // 1. Physics tick
      const isPetting = pettingRef.current;
      const speaking = isSpeakingRef.current;
      const isDrag = isDraggingRef.current;
      const container = containerRef.current;
      const cw = container?.clientWidth ?? 800;
      const ch = container?.clientHeight ?? 600;

      const shouldPausePhysics = (isPetting || speaking) && r.onGround;
      if (!shouldPausePhysics && !isDrag) {
        tickPhysics(r, platformsRef.current, dt, cw, ch);
      }

      // Detect dizzy landing → trigger land reaction
      const isDizzyNow = r.dizzy > 0;
      if (isDizzyNow && !wasDizzyRef.current) {
        triggerLand();
      }
      wasDizzyRef.current = isDizzyNow;

      // 2. Resolve position (streaming descend can override)
      const desc = descendRef.current;
      const useDescend = desc.active && !isPetting && !speaking;
      const posX = useDescend ? desc.x : r.x;
      const posY = useDescend ? desc.y : r.y;

      // 3. Update DOM position
      wrapper.style.transform = `translate(${Math.round(posX)}px, ${Math.round(posY)}px)`;

      // 4. Determine visual action
      let action: CatAction = r.action;
      if (isDrag) action = "grab";
      else if (r.clamberTarget) action = "clamber";
      else if (r.dizzy > 0) action = "dizzy";
      else if (isPetting) action = "pet";
      else if (useDescend) action = "walk";
      else if (r.falling && !r.onGround) action = "climb";

      // 5. CSS effects for fall / land / grab
      let spriteTransform = "";
      if (isDrag) {
        // Slight sway while being held
        const sway = Math.sin(now / 200) * 8;
        spriteTransform = `rotate(${sway.toFixed(1)}deg)`;
      } else if (isPetting) {
        spriteTransform = "scale(1.15)";
      } else if (r.landing > 0) {
        // Landing squish: starts at scaleY(0.7) scaleX(1.3), eases back
        const progress = r.landing / 220;
        const sy = 0.7 + 0.3 * (1 - progress);
        const sx = 1.3 - 0.3 * (1 - progress);
        spriteTransform = `scaleY(${sy.toFixed(2)}) scaleX(${sx.toFixed(2)})`;
      } else if (r.falling && r.vy > 2) {
        // Falling: tilt toward fall direction
        const tilt = r.facingRight ? 12 : -12;
        spriteTransform = `rotate(${tilt}deg)`;
      } else if (!r.onGround && r.vy < -1) {
        // Jumping up: slight upward tilt
        const tilt = r.facingRight ? -8 : 8;
        spriteTransform = `rotate(${tilt}deg)`;
      }
      spriteWrapper.style.transform = spriteTransform;
      spriteWrapper.style.transformOrigin = "center bottom";

      // 6. Reset animation clock on action change
      if (action !== lastActionRef.current) {
        lastActionRef.current = action;
        animStartRef.current = now;
      }

      // 7. Frame index
      const elapsed = now - animStartRef.current;
      const speed = ANIM_SPEEDS[action];
      const totalFrames = FRAME_COUNTS[action];
      const frameIndex = Math.floor(elapsed / speed) % totalFrames;

      // 8. Draw
      sprite.draw(action, frameIndex);
      const facingRight = useDescend ? desc.x > r.x : r.facingRight;
      sprite.setFlip(facingRight);

      rafRef.current = requestAnimationFrame(loop);
    },
    [roamingRef],
  );

  useEffect(() => {
    if (!enabled) return;
    prevTimeRef.current = 0;
    animStartRef.current = performance.now();
    rafRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(rafRef.current);
  }, [enabled, loop]);

  if (!enabled) {
    return (
      <div
        data-buddy-overlay
        style={{
          position: "absolute",
          right: 12,
          bottom: 12,
          zIndex: 5,
          pointerEvents: "auto",
        }}
      >
        <button
          onClick={toggle}
          title="显示桌面宠物"
          style={{
            width: 36,
            height: 36,
            borderRadius: "50%",
            border: "1px solid #E7ECF3",
            background: "rgba(255,255,255,0.9)",
            backdropFilter: "blur(8px)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 18,
            boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
            transition: "transform 0.15s, box-shadow 0.15s",
            opacity: 0.7,
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.opacity = "1";
            (e.currentTarget as HTMLButtonElement).style.transform = "scale(1.1)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.opacity = "0.7";
            (e.currentTarget as HTMLButtonElement).style.transform = "scale(1)";
          }}
        >
          🐱
        </button>
      </div>
    );
  }

  return (
    <div
      data-buddy-overlay
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: "100%",
        height: "100%",
        pointerEvents: "none",
        overflow: "hidden",
        zIndex: 5,
      }}
    >
      {/* Debug: platform visualization */}
      {debug && debugPlatforms.map((p, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: p.left,
            top: p.y - 1,
            width: p.right - p.left,
            height: 2,
            backgroundColor: i === 0 ? "red" : `hsl(${(i * 60) % 360}, 80%, 55%)`,
            opacity: 0.7,
            pointerEvents: "none",
          }}
        />
      ))}
      {debug && (
        <div style={{
          position: "absolute", top: 4, right: 4,
          fontSize: 10, color: "#f00", fontFamily: "monospace",
          background: "rgba(255,255,255,0.9)", padding: "2px 6px",
          borderRadius: 4, zIndex: 99,
        }}>
          {debugPlatforms.length} platforms
        </div>
      )}

      <div ref={wrapperRef} style={{ position: "absolute", willChange: "transform" }}>
        <div
          onContextMenu={handleContextMenu}
          style={{
            position: "relative",
            padding: "12px 16px 4px",
            margin: "-12px -16px -4px",
            pointerEvents: "auto",
          }}
        >
          <HeartBurst active={petting} />
          {reaction && (
            <SpeechBubble
              text={reaction}
              color={color}
              onRight={roamingRef.current.x > 200}
            />
          )}
          <div
            ref={spriteWrapperRef}
            onMouseDown={handleMouseDown}
            style={{
              transformOrigin: "center bottom",
              pointerEvents: "auto",
              cursor: isDragging ? "grabbing" : "grab",
              userSelect: "none",
            }}
          >
            <SpriteRenderer
              ref={spriteRef}
            />
          </div>
          <div
            onClick={() => !isDragging && setDebug((d) => !d)}
            style={{
              textAlign: "center",
              fontSize: "11px",
              color,
              fontWeight: 600,
              opacity: 0.85,
              marginTop: -2,
              pointerEvents: "auto",
              whiteSpace: "nowrap",
              textShadow: "0 1px 2px rgba(255,255,255,0.8)",
              cursor: isDragging ? "grabbing" : "pointer",
            }}
          >
            {companion.name}
          </div>
        </div>
      </div>

      {ctxMenu && (
        <PetContextMenu
          x={ctxMenu.x}
          y={ctxMenu.y}
          items={menuItems}
          onClose={closeCtxMenu}
        />
      )}
    </div>
  );
}

export default function RoamingPet({ containerRef, messages }: RoamingPetProps) {
  return (
    <BuddyErrorBoundary>
      <RoamingPetInner containerRef={containerRef} messages={messages} />
    </BuddyErrorBoundary>
  );
}
