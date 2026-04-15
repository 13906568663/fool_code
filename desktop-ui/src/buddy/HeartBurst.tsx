import { useEffect, useState } from "react";

interface Heart {
  id: number;
  x: number;
  delay: number;
  size: number;
}

export default function HeartBurst({ active }: { active: boolean }) {
  const [hearts, setHearts] = useState<Heart[]>([]);

  useEffect(() => {
    if (!active) {
      setHearts([]);
      return;
    }
    const burst: Heart[] = Array.from({ length: 6 }, (_, i) => ({
      id: Date.now() + i,
      x: -20 + Math.random() * 40,
      delay: Math.random() * 0.3,
      size: 12 + Math.random() * 8,
    }));
    setHearts(burst);
    const timer = setTimeout(() => setHearts([]), 2500);
    return () => clearTimeout(timer);
  }, [active]);

  if (hearts.length === 0) return null;

  return (
    <div
      style={{
        position: "absolute",
        top: -10,
        left: "50%",
        transform: "translateX(-50%)",
        pointerEvents: "none",
        width: 60,
        height: 60,
      }}
    >
      {hearts.map((h) => (
        <span
          key={h.id}
          style={{
            position: "absolute",
            left: `calc(50% + ${h.x}px)`,
            bottom: 0,
            fontSize: h.size,
            animation: `buddyHeartFloat 1.5s ease-out ${h.delay}s forwards`,
            opacity: 0,
          }}
        >
          ❤️
        </span>
      ))}
      <style>{`
        @keyframes buddyHeartFloat {
          0% { opacity: 1; transform: translateY(0) scale(0.5); }
          50% { opacity: 1; transform: translateY(-30px) scale(1); }
          100% { opacity: 0; transform: translateY(-55px) scale(0.8); }
        }
      `}</style>
    </div>
  );
}
