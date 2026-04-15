"""测试 JioNLP 中文时间解析能力 — 覆盖各种极端场景.

运行: uv run python tests/test_jionlp_time.py
"""

from __future__ import annotations

import json
from datetime import datetime

# ---------------------------------------------------------------------------
# Test cases: (query, description)
# 分几大类测试
# ---------------------------------------------------------------------------

BASIC_CASES = [
    ("今天", "当天"),
    ("昨天", "昨日"),
    ("前天", "前日"),
    ("明天", "明日"),
    ("后天", "后日"),
]

RELATIVE_WEEK = [
    ("这周", "本周"),
    ("上周", "上一周"),
    ("上上周", "上上周"),
    ("下周", "下一周"),
    ("这周末", "本周末 — 周六日"),
    ("上周末", "上周末"),
    ("周一", "最近的周一"),
    ("上周三", "上周三"),
    ("下周五", "下周五"),
]

RELATIVE_MONTH = [
    ("这个月", "本月"),
    ("上个月", "上月"),
    ("上上个月", "上上月 — 两个月前"),
    ("下个月", "下月"),
    ("3月", "3月 — 绝对月份"),
    ("三月", "三月 — 中文数字月份"),
    ("去年12月", "去年12月"),
]

RELATIVE_YEAR = [
    ("今年", "今年"),
    ("去年", "去年"),
    ("前年", "前年"),
]

COMPOSITE_EXPRESSIONS = [
    ("上上个月的周末", "两个月前的周末 — 复合"),
    ("3月的周末", "三月的周末 — 复合"),
    ("上周三下午", "上周三下午 — 复合"),
    ("去年国庆节", "去年国庆"),
    ("前天晚上", "前天晚上"),
    ("上个月月底", "上月底"),
    ("这周一到周三", "本周一至周三 — 区间"),
    ("最近三天", "最近3天 — 相对区间"),
    ("最近一周", "最近一周"),
    ("最近两个月", "最近两个月"),
    ("过去半年", "过去半年"),
]

SPECIFIC_DATES = [
    ("2026年3月15号", "具体日期"),
    ("3月15日", "省略年的日期"),
    ("2026-03-15", "ISO格式"),
    ("03/15", "斜杠格式"),
]

FESTIVAL_AND_SPECIAL = [
    ("春节", "春节"),
    ("中秋节", "中秋"),
    ("国庆节", "国庆"),
    ("元旦", "元旦"),
    ("五一", "劳动节"),
    ("双十一", "双十一"),
    ("除夕", "除夕"),
]

EMBEDDED_IN_SENTENCE = [
    ("我上上个月做了什么", "句子中的时间 — 上上个月"),
    ("3月周末我都在干嘛", "句子中的时间 — 3月周末"),
    ("帮我看看昨天下午的记录", "句子中的时间 — 昨天下午"),
    ("最近一个月我写了哪些代码", "句子中的时间 — 最近一个月"),
    ("去年夏天我们讨论过什么", "句子中的时间 — 去年夏天"),
    ("上周五开会说了什么", "句子中的时间 — 上周五"),
    ("前天和昨天我分别做了什么", "句子中多个时间"),
    ("从上周一到这周三的记录", "句子中的时间区间"),
]

EDGE_CASES = [
    ("大前天", "大前天 — 3天前"),
    ("上上上周", "上上上周 — 3周前"),
    ("上上上个月", "上上上个月 — 3个月前"),
    ("半个月前", "半个月前"),
    ("三天前", "3天前"),
    ("两小时前", "2小时前"),
    ("十分钟前", "10分钟前"),
    ("", "空字符串"),
    ("你好", "无时间信息的句子"),
    ("我在做一个项目", "完全无时间的句子"),
]

ALL_GROUPS = [
    ("基础相对日", BASIC_CASES),
    ("相对周", RELATIVE_WEEK),
    ("相对月", RELATIVE_MONTH),
    ("相对年", RELATIVE_YEAR),
    ("复合表达", COMPOSITE_EXPRESSIONS),
    ("具体日期", SPECIFIC_DATES),
    ("节假日", FESTIVAL_AND_SPECIAL),
    ("句子中嵌入时间", EMBEDDED_IN_SENTENCE),
    ("极端/边界", EDGE_CASES),
]


def test_jionlp_parse_time():
    """逐一测试 jionlp.parse_time 对每个 case 的解析结果."""
    try:
        import jionlp as jio
    except ImportError:
        print("❌ jionlp 未安装，请先: uv add jionlp")
        return

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    print(f"当前时间: {now_str}\n")

    total = 0
    success = 0
    fail = 0
    no_result = 0

    for group_name, cases in ALL_GROUPS:
        print(f"\n{'='*60}")
        print(f"  {group_name}")
        print(f"{'='*60}")

        for query, desc in cases:
            total += 1
            print(f"\n  输入: 「{query}」  ({desc})")
            try:
                result = jio.parse_time(query, time_base=now)
                if result:
                    print(f"  ✅ 结果: {json.dumps(result, ensure_ascii=False, indent=6)}")
                    success += 1
                else:
                    print(f"  ⚠️  无结果 (返回 None / 空)")
                    no_result += 1
            except Exception as e:
                print(f"  ❌ 异常: {type(e).__name__}: {e}")
                fail += 1

    print(f"\n\n{'='*60}")
    print(f"  统计: 共 {total} 个用例")
    print(f"  ✅ 成功解析: {success}")
    print(f"  ⚠️  无结果:   {no_result}")
    print(f"  ❌ 异常:     {fail}")
    print(f"{'='*60}")


def test_extract_from_sentence():
    """测试从完整句子中抽取时间表达式的能力."""
    try:
        import jionlp as jio
    except ImportError:
        print("❌ jionlp 未安装")
        return

    now = datetime.now()
    sentences = [
        "我上上个月做了什么",
        "3月周末我都在干嘛",
        "帮我看看昨天下午的记录",
        "最近一个月我写了哪些代码",
        "去年夏天我们讨论过什么",
        "上周五开会说了什么",
        "前天和昨天我分别做了什么",
        "从上周一到这周三的记录",
        "我2025年3月15号写的那个bug修了没",
        "上上个月的第一个周末我在干嘛",
    ]

    print(f"\n\n{'='*60}")
    print(f"  从句子中提取时间表达式")
    print(f"{'='*60}")

    for s in sentences:
        print(f"\n  句子: 「{s}」")
        try:
            result = jio.parse_time(s, time_base=now)
            if result:
                print(f"  解析: {json.dumps(result, ensure_ascii=False, indent=6)}")
            else:
                print(f"  ⚠️  无法解析")
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")


def test_time_range_output_format():
    """验证 parse_time 返回的数据结构，确定如何转成 (start_ts, end_ts)."""
    try:
        import jionlp as jio
    except ImportError:
        print("❌ jionlp 未安装")
        return

    now = datetime.now()
    test_inputs = ["昨天", "上周", "上个月", "最近三天", "3月15日"]

    print(f"\n\n{'='*60}")
    print(f"  返回结构分析 (用于确定如何集成)")
    print(f"{'='*60}")

    for inp in test_inputs:
        print(f"\n  输入: 「{inp}」")
        try:
            result = jio.parse_time(inp, time_base=now)
            print(f"  type={type(result).__name__}")
            print(f"  value={result}")
            if isinstance(result, dict):
                for k, v in result.items():
                    print(f"    {k}: {v!r} (type={type(v).__name__})")
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")


if __name__ == "__main__":
    test_jionlp_parse_time()
    test_extract_from_sentence()
    test_time_range_output_format()
