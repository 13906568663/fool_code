import { useCallback, useEffect, useRef } from "react";
import type { CatAction } from "./SpriteRenderer";
import type { Platform } from "./platformScanner";

export interface RoamingRefs {
  x: number;
  y: number;
  vx: number;
  vy: number;
  onGround: boolean;
  currentPlatform: Platform | null;
  facingRight: boolean;
  action: CatAction;
  /** >0 while landing squish animation plays (ms remaining) */
  landing: number;
  /** True while falling downward */
  falling: boolean;
  /** True while being dragged — used to trigger dizzy on landing */
  wasGrabbed: boolean;
  /** Y position when grab was released, used to measure fall distance */
  grabReleaseY: number;
  /** >0 while dizzy animation plays (ms remaining) */
  dizzy: number;
  /** Clamber state: target platform, progress timer */
  clamberTarget: Platform | null;
  clamberTime: number;
  clamberStartX: number;
  clamberStartY: number;
}

const SPRITE_W = 64;
const SPRITE_H = 72;
const GRAVITY = 0.35;
const WALK_SPEED = 1.2;
const JUMP_VY = -14;
const TERMINAL_VY = 9;
const LANDING_DURATION = 220;
const DIZZY_DURATION = 1800;
const CLAMBER_DURATION = 2400;
const MAX_JUMP_HEIGHT = (JUMP_VY * JUMP_VY) / (2 * GRAVITY); // ~280px

// ---------------------------------------------------------------------------
// Physics tick — called every rAF frame
// ---------------------------------------------------------------------------

export function tickPhysics(
  r: RoamingRefs,
  platforms: Platform[],
  dt: number,
  containerW: number,
  containerH: number,
): void {
  // Clamber animation — walk under platform, then climb up
  if (r.clamberTarget && r.clamberTime > 0) {
    r.clamberTime = Math.max(0, r.clamberTime - dt);
    const progress = 1 - r.clamberTime / CLAMBER_DURATION;
    const targetX = (r.clamberTarget.left + r.clamberTarget.right) / 2 - SPRITE_W / 2;
    const targetY = r.clamberTarget.y - SPRITE_H;

    if (progress < 0.25) {
      const hProgress = progress / 0.25;
      r.x = r.clamberStartX + (targetX - r.clamberStartX) * hProgress;
      r.y = r.clamberStartY;
    } else {
      const vProgress = (progress - 0.25) / 0.75;
      const ease = vProgress < 0.5
        ? 2 * vProgress * vProgress
        : 1 - Math.pow(-2 * vProgress + 2, 2) / 2;
      r.x = targetX;
      r.y = r.clamberStartY + (targetY - r.clamberStartY) * ease;
    }

    if (r.clamberTime <= 0) {
      r.x = targetX;
      r.y = targetY;
      r.onGround = true;
      r.currentPlatform = r.clamberTarget;
      r.clamberTarget = null;
      r.vy = 0;
      r.vx = 0;
      r.falling = false;
      r.action = "idle";
    }
    return;
  }

  // Dizzy animation countdown
  if (r.dizzy > 0) {
    r.dizzy = Math.max(0, r.dizzy - dt);
    if (r.dizzy <= 0) {
      r.action = "idle";
    }
    if (r.onGround) return;
    // If not on ground, fall through to gravity/collision below
  }

  // Landing animation countdown
  if (r.landing > 0) {
    r.landing = Math.max(0, r.landing - dt);
    if (r.onGround) return;
  }

  // Validate current platform still exists — prevents floating
  if (r.onGround && r.currentPlatform) {
    const cp = r.currentPlatform;
    const stillExists = platforms.some(
      (p) => Math.abs(p.y - cp.y) < 15 && p.left <= cp.right && p.right >= cp.left,
    );
    if (!stillExists) {
      r.onGround = false;
      r.currentPlatform = null;
      r.falling = true;
      r.vy = 0.5;
    }
  }

  // Gravity
  if (!r.onGround) {
    r.vy = Math.min(r.vy + GRAVITY, TERMINAL_VY);
    r.falling = r.vy > 0;
  }

  // Horizontal movement
  if (r.action === "walk" && r.onGround) {
    r.x += r.facingRight ? WALK_SPEED : -WALK_SPEED;
  }
  // Airborne horizontal momentum
  if (!r.onGround) {
    r.x += r.vx;
  }

  // Vertical movement
  const prevBottom = r.y + SPRITE_H;
  r.y += r.vy;
  const newBottom = r.y + SPRITE_H;

  // Platform collision (only when moving downward)
  if (r.vy >= 0) {
    let landed = false;
    for (const p of platforms) {
      const horizontalOverlap = r.x + SPRITE_W > p.left + 8 && r.x < p.right - 8;
      if (
        horizontalOverlap &&
        prevBottom <= p.y + 2 &&
        newBottom >= p.y
      ) {
        r.y = p.y - SPRITE_H;
        r.onGround = true;
        r.currentPlatform = p;
        if (r.falling && r.wasGrabbed) {
          const fallDist = r.y - r.grabReleaseY;
          r.wasGrabbed = false;
          if (fallDist > 120) {
            r.dizzy = DIZZY_DURATION;
            r.action = "dizzy";
          } else {
            r.landing = LANDING_DURATION;
            r.action = "idle";
          }
        } else if (r.falling) {
          r.landing = LANDING_DURATION;
          r.action = "idle";
        }
        r.vy = 0;
        r.vx = 0;
        r.falling = false;
        landed = true;
        break;
      }
    }

    // Fallback: if somehow fell way below container, reset
    if (!landed && r.y > containerH + 200) {
      r.x = containerW / 2 - SPRITE_W / 2;
      r.y = 20;
      r.vy = 0;
      r.vx = 0;
      r.onGround = false;
      r.falling = true;
    }
  }

  // Edge detection: walked off platform
  if (r.onGround && r.currentPlatform) {
    const p = r.currentPlatform;
    if (r.x + SPRITE_W < p.left + 4 || r.x > p.right - 4) {
      r.onGround = false;
      r.currentPlatform = null;
      r.action = "climb";
      r.falling = true;
      r.vx = r.facingRight ? 0.5 : -0.5;
    }
  }

  // Boundary clamping — keep cat inside container
  if (r.x < 0) {
    r.x = 0;
    r.vx = Math.abs(r.vx) * 0.3;
    r.facingRight = true;
  } else if (r.x > containerW - SPRITE_W) {
    r.x = containerW - SPRITE_W;
    r.vx = -Math.abs(r.vx) * 0.3;
    r.facingRight = false;
  }

  if (r.y < 0) {
    r.y = 0;
    r.vy = Math.abs(r.vy) * 0.3;
  } else if (r.y > containerH - SPRITE_H) {
    r.y = containerH - SPRITE_H;
    r.vy = 0;
    r.onGround = true;
    r.falling = false;
    // Find the floor platform and set it as current
    const floorY = r.y + SPRITE_H;
    const floor = platforms.find((p) => Math.abs(p.y - floorY) < 20);
    if (floor) r.currentPlatform = floor;
    if (r.action === "climb") r.action = "idle";
  }
}

// ---------------------------------------------------------------------------
// Behavior decisions
// ---------------------------------------------------------------------------

function isSamePlatform(a: Platform, b: Platform): boolean {
  return Math.abs(a.y - b.y) < 15 &&
    Math.abs(a.left - b.left) < 30 &&
    Math.abs(a.right - b.right) < 30;
}

function tryJump(r: RoamingRefs, platforms: Platform[]): boolean {
  if (!r.onGround) return false;
  const curY = r.currentPlatform ? r.currentPlatform.y : r.y + SPRITE_H;
  const curCenterX = r.x + SPRITE_W / 2;

  // Split candidates into "above" and "below"
  const above: Platform[] = [];
  const below: Platform[] = [];

  for (const p of platforms) {
    if (r.currentPlatform && isSamePlatform(p, r.currentPlatform)) continue;
    if (!r.currentPlatform && Math.abs(p.y - curY) < 15) continue;

    const dy = curY - p.y; // positive = platform is above (smaller y)
    const pCenterX = (p.left + p.right) / 2;
    const dx = Math.abs(pCenterX - curCenterX);

    if (dy > 10 && dy <= MAX_JUMP_HEIGHT * 0.85 && dx < 500) {
      above.push(p);
    } else if (dy < -10 && dy > -400 && dx < 500) {
      below.push(p);
    }
  }

  const all = [...above, ...below];
  if (all.length === 0) return false;

  // Prefer above 60% of the time
  let target: Platform;
  if (above.length > 0 && (below.length === 0 || Math.random() < 0.6)) {
    target = above[Math.floor(Math.random() * above.length)]!;
  } else if (below.length > 0) {
    target = below[Math.floor(Math.random() * below.length)]!;
  } else {
    return false;
  }

  const pCenterX = (target.left + target.right) / 2;
  const dx = pCenterX - curCenterX;
  const dy = curY - target.y;

  if (dy > 0) {
    // Jump UP: need enough vy to reach the height
    const neededVy = -Math.sqrt(2 * GRAVITY * (dy + 20));
    const airTime = Math.abs(neededVy * 2) / GRAVITY;
    r.vy = Math.min(neededVy, JUMP_VY);
    r.vx = (dx / airTime) * 0.8;
  } else {
    // Jump DOWN: small hop then fall
    r.vy = JUMP_VY * 0.35;
    const fallDist = Math.abs(dy);
    const fallTime = Math.sqrt(2 * fallDist / GRAVITY) + 10;
    r.vx = dx / fallTime;
  }

  // Cap vx for reasonable arcs
  r.vx = Math.max(-4, Math.min(4, r.vx));
  r.facingRight = r.vx > 0;
  r.onGround = false;
  r.currentPlatform = null;
  r.action = "climb";
  return true;
}

function tryDropDown(r: RoamingRefs, platforms: Platform[]): boolean {
  if (!r.onGround) return false;
  const curY = r.currentPlatform ? r.currentPlatform.y : r.y + SPRITE_H;

  const below = platforms.filter((p) => {
    if (r.currentPlatform && isSamePlatform(p, r.currentPlatform)) return false;
    if (!r.currentPlatform && Math.abs(p.y - curY) < 15) return false;
    const dy = p.y - curY;
    return dy > 30 && dy < 250;
  });

  if (below.length === 0) return false;
  const target = below[Math.floor(Math.random() * below.length)]!;
  const pCenterX = (target.left + target.right) / 2;
  const curCenterX = r.x + SPRITE_W / 2;

  // Walk toward edge then step off
  r.facingRight = pCenterX > curCenterX;
  r.action = "walk";
  return true;
}

function tryClamber(r: RoamingRefs, platforms: Platform[]): boolean {
  if (!r.onGround) return false;
  const curY = r.currentPlatform ? r.currentPlatform.y : r.y + SPRITE_H;
  const curCenterX = r.x + SPRITE_W / 2;

  // Find platforms directly above, within horizontal reach
  const above = platforms.filter((p) => {
    if (r.currentPlatform && isSamePlatform(p, r.currentPlatform)) return false;
    const dy = curY - p.y;
    const pCenterX = (p.left + p.right) / 2;
    const dx = Math.abs(pCenterX - curCenterX);
    return dy > 40 && dy <= 400 && dx < 400;
  });

  if (above.length === 0) return false;
  const target = above[Math.floor(Math.random() * above.length)]!;

  r.clamberTarget = target;
  r.clamberTime = CLAMBER_DURATION;
  r.clamberStartX = r.x;
  r.clamberStartY = r.y;
  r.onGround = false;
  r.currentPlatform = null;
  r.action = "clamber";
  r.facingRight = (target.left + target.right) / 2 > curCenterX;
  return true;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useRoaming(
  containerRef: React.RefObject<HTMLDivElement | null>,
  paused: boolean,
  petting: boolean,
  sleeping: boolean,
  platformsRef: React.MutableRefObject<Platform[]>,
): React.MutableRefObject<RoamingRefs> {
  const refs = useRef<RoamingRefs>({
    x: 100, y: 0,
    vx: 0, vy: 0,
    onGround: false,
    currentPlatform: null,
    facingRight: true,
    action: "idle",
    landing: 0,
    falling: true,
    wasGrabbed: false,
    grabReleaseY: 0,
    dizzy: 0,
    clamberTarget: null,
    clamberTime: 0,
    clamberStartX: 0,
    clamberStartY: 0,
  });
  const initialized = useRef(false);
  const behaviorTimer = useRef<ReturnType<typeof setTimeout>>();
  const pendingTimers = useRef<ReturnType<typeof setTimeout>[]>([]);

  // Initialize: start near top-center, let gravity pull down
  useEffect(() => {
    const el = containerRef.current;
    if (!el || initialized.current) return;
    const rect = el.getBoundingClientRect();
    const r = refs.current;
    r.x = rect.width / 2 - SPRITE_W / 2;
    r.y = 20;
    r.vy = 0;
    r.falling = true;
    r.onGround = false;
    initialized.current = true;
  }, [containerRef]);

  const scheduleBehavior = useCallback(() => {
    const delay = 1200 + Math.random() * 3000;
    behaviorTimer.current = setTimeout(() => {
      const r = refs.current;
      if (!r.onGround || r.landing > 0 || r.dizzy > 0 || r.clamberTarget) {
        scheduleBehavior();
        return;
      }

      const platforms = platformsRef.current;
      const hasManyPlatforms = platforms.length > 2;
      const roll = Math.random();

      if (roll < 0.15) {
        r.facingRight = Math.random() > 0.5;
        r.action = "walk";
        const t = setTimeout(() => {
          if (r.action === "walk") r.action = "idle";
        }, 800 + Math.random() * 1600);
        pendingTimers.current.push(t);
      } else if (roll < 0.25) {
        r.action = "idle";
      } else if (roll < (hasManyPlatforms ? 0.50 : 0.35)) {
        const jumped = tryJump(r, platforms);
        if (!jumped) {
          r.facingRight = Math.random() > 0.5;
          r.action = "walk";
          const t = setTimeout(() => {
            if (r.action === "walk") r.action = "idle";
          }, 500);
          pendingTimers.current.push(t);
        }
      } else if (roll < (hasManyPlatforms ? 0.85 : 0.70)) {
        if (!tryClamber(r, platforms)) {
          tryJump(r, platforms);
        }
      } else if (roll < (hasManyPlatforms ? 0.90 : 0.75)) {
        if (!tryDropDown(r, platforms)) {
          tryJump(r, platforms);
        }
      } else {
        r.action = "sit";
        const t = setTimeout(() => {
          if (r.action === "sit") r.action = "idle";
        }, 2000 + Math.random() * 2500);
        pendingTimers.current.push(t);
      }

      scheduleBehavior();
    }, delay);
  }, [platformsRef]);

  // Override for petting / sleeping
  useEffect(() => {
    if (petting) {
      const r = refs.current;
      r.action = "pet";
      r.vx = 0;
    }
  }, [petting]);

  useEffect(() => {
    if (sleeping) {
      const r = refs.current;
      r.action = "sleep";
      r.vx = 0;
    }
  }, [sleeping]);

  // Behavior loop
  useEffect(() => {
    if (paused || petting || sleeping) return;
    scheduleBehavior();
    return () => {
      if (behaviorTimer.current) clearTimeout(behaviorTimer.current);
      pendingTimers.current.forEach(clearTimeout);
      pendingTimers.current = [];
    };
  }, [paused, petting, sleeping, scheduleBehavior]);

  return refs;
}
