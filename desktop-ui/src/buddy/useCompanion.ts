import { useCallback, useEffect, useRef, useState } from "react";
import { getCompanion } from "./companion";
import { buddyChat } from "../services/api";

const FALLBACK_REACTIONS = [
  "嗯嗯，继续说~",
  "这个写法很妙！",
  "我看到 bug 了吗？",
  "加油加油！",
  "让我想想…",
  "代码看起来不错~",
  "要不要休息一下？",
  "这个重构好评！",
  "哇，好长的报错…",
  "我帮不上忙但我支持你！",
  "是不是该 commit 了？",
  "这段逻辑有点绕哦",
  "我闻到了 coffee 的味道",
  "喵~",
  "(打了个哈欠)",
  "这里可以优化一下哦",
  "主人主人！看我看我！",
  "主人今天也很厉害呢~",
  "主人摸摸我嘛~",
  "主人写代码好认真，好帅！",
  "(蹭蹭主人的手)",
  "主人别太累了喵…",
  "等主人忙完陪我玩好不好~",
  "主人是全世界最好的主人！",
  "(趴在主人键盘旁边打呼噜)",
  "主人的代码闻起来香香的~",
  "我就静静看着主人就好~",
  "主人今天喝水了吗？",
  "(歪头) 主人在想什么呀？",
  "主人加油！我给你捶背喵~",
  "别的猫都没有我主人厉害！",
];

const AI_PROMPTS = [
  "你想引起主人注意，撒个娇吧",
  "你刚睡醒发现主人还在，很开心，说点什么",
  "你觉得主人好久没理你了，有点委屈",
  "你想夸主人，用你笨拙的方式",
  "你想让主人摸摸你，求一下",
  "你看到主人打字好快，崇拜地说点什么",
  "你想提醒主人该喝水了，用撒娇的方式",
  "你趴在主人旁边好无聊，发出一句傻话",
  "你怀疑主人是不是在看别的猫，吃醋了",
  "你蹭了蹭主人的手，说一句甜甜的话",
  "你想告诉主人你最喜欢主人了",
  "你看着主人觉得好帅/好美，表达一下",
  "你犯傻了，说了一句让人哭笑不得的话",
  "你假装自己在帮主人debug",
  "你闻到主人身上的味道，觉得好安心",
  "你竖起尾巴开心地说点什么",
  "你想和主人分享你今天的小发现",
  "你假装很酷但其实很黏人",
  "你偷偷观察主人写代码，装作很懂的样子评价一下",
  "你打了个哈欠但又舍不得睡，因为想多看主人一眼",
];

const GRAB_REACTIONS = [
  "呜啊啊！放我下来！",
  "喵呜！！被抓住了！",
  "主人轻点轻点！",
  "哇啊——我恐高！",
  "救命！猫猫要飞了！",
  "放…放开朕！",
  "我不是抓娃娃啦！",
  "尾巴！注意我尾巴！",
  "(四脚乱蹬)",
  "主人又欺负我呜呜~",
  "天旋地转喵！！",
  "我还以为我会飞…",
];

const LAND_REACTIONS = [
  "呜…好晕…",
  "(摔了个屁股蹲)",
  "喵的！摔疼了！",
  "还好有九条命…",
  "我没事…才怪！",
  "头好晕，转圈圈…",
  "着陆失败…喵…",
  "(趴地上装死)",
  "下次能不能温柔点…",
  "好疼…主人赔我小鱼干！",
  "猫生走马灯了喵…",
  "安全着陆！才怪！",
];

const SLEEP_AFTER_MS = 60000;

function randomFallback(): string {
  return FALLBACK_REACTIONS[Math.floor(Math.random() * FALLBACK_REACTIONS.length)]!;
}

export function useCompanion() {
  const [companion] = useState(() => getCompanion());
  const [reaction, setReaction] = useState<string>();
  const [petting, setPetting] = useState(false);
  const [sleeping, setSleeping] = useState(false);
  const [enabled, setEnabled] = useState(() => {
    return localStorage.getItem("fool-code-buddy-enabled") !== "false";
  });
  const reactionTimer = useRef<ReturnType<typeof setTimeout>>();
  const autoReactionTimer = useRef<ReturnType<typeof setTimeout>>();
  const lastActivityRef = useRef(Date.now());
  const sleepCheckRef = useRef<ReturnType<typeof setInterval>>();
  const aiPendingRef = useRef(false);

  const wakeUp = useCallback(() => {
    lastActivityRef.current = Date.now();
    setSleeping(false);
  }, []);

  const showReaction = useCallback(
    (text: string) => {
      if (reactionTimer.current) clearTimeout(reactionTimer.current);
      setReaction(text);
      reactionTimer.current = setTimeout(() => setReaction(undefined), 8000);
    },
    [],
  );

  const triggerReaction = useCallback(
    (text?: string) => {
      wakeUp();
      showReaction(text ?? randomFallback());
    },
    [wakeUp, showReaction],
  );

  const triggerAIReaction = useCallback(async () => {
    if (aiPendingRef.current) return;
    aiPendingRef.current = true;
    try {
      const prompt = AI_PROMPTS[Math.floor(Math.random() * AI_PROMPTS.length)]!;
      const text = await buddyChat(prompt, companion.name);
      if (text) {
        showReaction(text);
      } else {
        showReaction(randomFallback());
      }
    } catch {
      showReaction(randomFallback());
    } finally {
      aiPendingRef.current = false;
    }
  }, [companion.name, showReaction]);

  const pet = useCallback(() => {
    wakeUp();
    setPetting(true);
    showReaction("❤️ 喵~嘿嘿~");
    setTimeout(() => setPetting(false), 2500);
  }, [wakeUp, showReaction, companion.name]);

  const triggerGrab = useCallback(() => {
    wakeUp();
    showReaction(GRAB_REACTIONS[Math.floor(Math.random() * GRAB_REACTIONS.length)]!);
  }, [wakeUp, showReaction]);

  const triggerLand = useCallback(() => {
    showReaction(LAND_REACTIONS[Math.floor(Math.random() * LAND_REACTIONS.length)]!);
  }, [showReaction]);

  const toggle = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev;
      localStorage.setItem("fool-code-buddy-enabled", String(next));
      return next;
    });
  }, []);

  // Sleep detection
  useEffect(() => {
    if (!enabled) return;
    sleepCheckRef.current = setInterval(() => {
      if (Date.now() - lastActivityRef.current > SLEEP_AFTER_MS) {
        setSleeping(true);
      }
    }, 10000);
    return () => {
      if (sleepCheckRef.current) clearInterval(sleepCheckRef.current);
    };
  }, [enabled]);

  // Track user activity
  useEffect(() => {
    if (!enabled) return;
    const onActivity = () => {
      lastActivityRef.current = Date.now();
      setSleeping(false);
    };
    window.addEventListener("keydown", onActivity);
    window.addEventListener("mousedown", onActivity);
    return () => {
      window.removeEventListener("keydown", onActivity);
      window.removeEventListener("mousedown", onActivity);
    };
  }, [enabled]);

  // Auto reactions — using local random (set useAI = true to enable AI)
  const useAI = false;
  useEffect(() => {
    if (!enabled) return;
    const scheduleNext = () => {
      const delay = 20000 + Math.random() * 40000;
      autoReactionTimer.current = setTimeout(() => {
        if (!sleeping) {
          if (useAI) {
            triggerAIReaction();
          } else {
            triggerReaction();
          }
        }
        scheduleNext();
      }, delay);
    };
    const initial = setTimeout(() => {
      triggerReaction("嗨~ 我是 " + companion.name + "！喵~");
      scheduleNext();
    }, 3000);
    return () => {
      clearTimeout(initial);
      if (autoReactionTimer.current) clearTimeout(autoReactionTimer.current);
    };
  }, [enabled, sleeping, companion.name, triggerReaction, triggerAIReaction]);

  return {
    companion,
    reaction,
    petting,
    sleeping,
    enabled,
    pet,
    toggle,
    triggerReaction,
    triggerGrab,
    triggerLand,
    wakeUp,
  };
}
