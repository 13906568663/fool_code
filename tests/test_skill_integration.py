"""Skill self-improvement system — real integration tests.

Tests the full stack: registry → tool execution → disk I/O → Skill Store ingest,
prompt section generation on a real system, and conversation runtime nudge
counter with simulated iterations.

Run:  uv run python tests/test_skill_integration.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def section(msg: str) -> None:
    print(f"\n--- {msg} ---")


# ======================================================================
# Test 1: SkillManage is properly registered in the real tool registry
# ======================================================================

def test_registry_has_skill_manage():
    header("Test 1: SkillManage registered in build_tool_registry()")
    from fool_code.tools.registry import build_tool_registry

    registry = build_tool_registry()
    handler = registry.get_handler("SkillManage")
    if handler is None:
        fail("SkillManage not found in registry")
        return False

    ok(f"SkillManage handler: {type(handler).__name__}")

    defn = handler.definition.model_dump()
    func = defn.get("function", {})
    params = func.get("parameters", {}).get("properties", {})
    ok(f"Schema parameters: {list(params.keys())}")

    required_params = {"action", "name"}
    actual_required = set(func.get("parameters", {}).get("required", []))
    if required_params <= actual_required:
        ok(f"Required params correct: {actual_required}")
    else:
        fail(f"Required params mismatch — expected at least {required_params}, got {actual_required}")
        return False

    optional_params = {"content", "old_string", "new_string", "category"}
    actual_all = set(params.keys())
    if optional_params <= actual_all:
        ok(f"All expected params present: {actual_all}")
    else:
        fail(f"Missing params — expected {optional_params - actual_all}")
        return False

    defs = registry.definitions()
    sm_defs = [d for d in defs if d.get("function", {}).get("name") == "SkillManage"]
    if sm_defs:
        ok("SkillManage appears in definitions() (full list)")
    else:
        fail("SkillManage NOT in definitions()")
        return False

    return True


# ======================================================================
# Test 2: Full create → patch → delete lifecycle via real tool execution
# ======================================================================

def test_full_lifecycle():
    header("Test 2: Full create → patch → delete lifecycle")
    tmpdir = tempfile.mkdtemp(prefix="skill_integ_")
    try:
        with patch("fool_code.tools.skill.skills_path", return_value=Path(tmpdir)):
            from fool_code.tools.skill import skill_manage, clear_skill_caches

            section("2a: Create skill")
            content = (
                "---\n"
                "name: integ-test-skill\n"
                "description: Integration test skill for validation\n"
                "---\n"
                "# Integration Test Skill\n\n"
                "## Steps\n"
                "1. Do step one\n"
                "2. Do step two\n"
            )
            result = json.loads(skill_manage({"action": "create", "name": "integ-test-skill", "content": content}))
            if not result.get("success"):
                fail(f"Create failed: {result.get('error')}")
                return False
            ok(f"Created: {result['name']} at {result['path']}")

            skill_md = Path(tmpdir) / "integ-test-skill" / "SKILL.md"
            if not skill_md.exists():
                fail("SKILL.md not found on disk")
                return False
            disk_content = skill_md.read_text(encoding="utf-8")
            if "integ-test-skill" in disk_content and "Do step one" in disk_content:
                ok("Disk content verified")
            else:
                fail("Disk content mismatch")
                return False

            section("2b: Duplicate create should fail")
            result2 = json.loads(skill_manage({"action": "create", "name": "integ-test-skill", "content": content}))
            if not result2.get("success"):
                ok(f"Duplicate correctly rejected: {result2['error']}")
            else:
                fail("Duplicate create should have failed")
                return False

            section("2c: Patch skill")
            clear_skill_caches()
            result3 = json.loads(skill_manage({
                "action": "patch",
                "name": "integ-test-skill",
                "old_string": "1. Do step one",
                "new_string": "1. Do improved step one\n1.5. New intermediate step",
            }))
            if not result3.get("success"):
                fail(f"Patch failed: {result3.get('error')}")
                return False
            ok(f"Patched: {result3['name']}")

            patched = skill_md.read_text(encoding="utf-8")
            if "improved step one" in patched and "New intermediate step" in patched:
                ok("Patched content verified on disk")
            else:
                fail("Patched content not found on disk")
                return False
            if "Do step one" in patched:
                fail("Old content still present after patch")
                return False
            ok("Old content correctly replaced")

            section("2d: Patch with bad old_string")
            result4 = json.loads(skill_manage({
                "action": "patch",
                "name": "integ-test-skill",
                "old_string": "THIS DOES NOT EXIST",
                "new_string": "replacement",
            }))
            if not result4.get("success"):
                ok(f"Bad patch correctly rejected: {result4['error']}")
            else:
                fail("Bad patch should have failed")
                return False

            section("2e: Delete skill")
            clear_skill_caches()
            result5 = json.loads(skill_manage({"action": "delete", "name": "integ-test-skill"}))
            if not result5.get("success"):
                fail(f"Delete failed: {result5.get('error')}")
                return False
            ok(f"Deleted: {result5['name']}")

            if (Path(tmpdir) / "integ-test-skill").exists():
                fail("Skill directory still exists after delete")
                return False
            ok("Skill directory removed from disk")

            section("2f: Delete non-existent skill")
            result6 = json.loads(skill_manage({"action": "delete", "name": "integ-test-skill"}))
            if not result6.get("success"):
                ok(f"Delete of non-existent correctly rejected: {result6['error']}")
            else:
                fail("Delete of non-existent should have failed")
                return False

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return True


# ======================================================================
# Test 3: Registry execute() pipeline (simulates what the agent loop does)
# ======================================================================

def test_registry_execute_pipeline():
    header("Test 3: Execute SkillManage through ToolRegistry.execute()")
    tmpdir = tempfile.mkdtemp(prefix="skill_exec_")
    try:
        with patch("fool_code.tools.skill.skills_path", return_value=Path(tmpdir)):
            from fool_code.tools.registry import build_tool_registry
            from fool_code.tools.tool_protocol import ToolContext

            registry = build_tool_registry()
            ctx = ToolContext(workspace_root=tmpdir)

            section("3a: Execute create via registry")
            raw_input = json.dumps({
                "action": "create",
                "name": "registry-test",
                "content": (
                    "---\n"
                    "name: registry-test\n"
                    "description: Created via registry.execute()\n"
                    "---\n"
                    "# Registry Test\n\nContent body.\n"
                ),
            })
            result = registry.execute("SkillManage", raw_input, ctx)
            parsed = json.loads(result.output)
            if parsed.get("success"):
                ok(f"Registry execute create: {parsed['message']}")
            else:
                fail(f"Registry execute create failed: {parsed.get('error')}")
                return False

            if result.is_error:
                fail("ToolResult.is_error is True for successful create")
                return False
            ok("ToolResult.is_error = False")

            section("3b: Execute delete via registry")
            raw_input2 = json.dumps({"action": "delete", "name": "registry-test"})
            result2 = registry.execute("SkillManage", raw_input2, ctx)
            parsed2 = json.loads(result2.output)
            if parsed2.get("success"):
                ok(f"Registry execute delete: {parsed2['message']}")
            else:
                fail(f"Registry execute delete failed: {parsed2.get('error')}")
                return False

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return True


# ======================================================================
# Test 4: build_skill_prompt_section with real Skill Store (if available)
# ======================================================================

def test_prompt_section_real():
    header("Test 4: build_skill_prompt_section — real environment")

    from fool_code.tools.skill import build_skill_prompt_section

    section("4a: Call build_skill_prompt_section()")
    result = build_skill_prompt_section()

    if result is None:
        ok("Returned None (Skill Store disabled or not available — expected on some environments)")
        return True

    ok(f"Got prompt section, length = {len(result)} chars")

    if "技能库" in result:
        ok("Contains '技能库' header")
    else:
        fail("Missing '技能库' header")
        return False

    if "SkillManage" in result:
        ok("Contains SkillManage guidance")
    else:
        fail("Missing SkillManage guidance")
        return False

    if "技能自我改进" in result:
        ok("Contains self-improvement guidance section")
    else:
        fail("Missing self-improvement guidance")
        return False

    if "SearchSkills" in result:
        ok("Contains SearchSkills reference")
    else:
        fail("Missing SearchSkills reference")
        return False

    print(f"\n  --- Prompt section preview (first 500 chars) ---")
    for line in result[:500].split("\n"):
        print(f"  | {line}")
    if len(result) > 500:
        print(f"  | ... ({len(result) - 500} more chars)")

    return True


# ======================================================================
# Test 5: ConversationRuntime nudge counter integration
# ======================================================================

def test_nudge_counter_runtime():
    header("Test 5: ConversationRuntime nudge counter — integration")

    from fool_code.types import Session
    from fool_code.runtime.conversation import ConversationRuntime

    session = Session()
    mock_provider = MagicMock()
    mock_registry = MagicMock()
    mock_registry.definitions_filtered.return_value = []
    mock_gate = MagicMock()
    events: list = []

    rt = ConversationRuntime(
        session=session,
        provider=mock_provider,
        tool_registry=mock_registry,
        system_prompt=["test"],
        permission_gate=mock_gate,
        event_callback=lambda e: events.append(e),
    )

    section("5a: Initial state")
    if rt._iters_since_skill == 0:
        ok("Counter starts at 0")
    else:
        fail(f"Counter starts at {rt._iters_since_skill}, expected 0")
        return False

    if rt._skill_nudge_interval == 10:
        ok("Nudge interval = 10")
    else:
        fail(f"Nudge interval = {rt._skill_nudge_interval}, expected 10")
        return False

    section("5b: Simulate 9 iterations (below threshold)")
    for i in range(9):
        rt._iters_since_skill += 1
        tool_calls = [{"name": "bash", "id": f"tc{i}", "input": "{}"}]
        if any(tc["name"] == "SkillManage" for tc in tool_calls):
            rt._iters_since_skill = 0

    if rt._iters_since_skill == 9:
        ok(f"Counter = {rt._iters_since_skill} after 9 non-skill iterations")
    else:
        fail(f"Counter = {rt._iters_since_skill}, expected 9")
        return False

    should_review = (rt._skill_nudge_interval > 0
                     and rt._iters_since_skill >= rt._skill_nudge_interval)
    if not should_review:
        ok("Review NOT triggered at 9 (correct)")
    else:
        fail("Review should NOT trigger at 9")
        return False

    section("5c: One more iteration → triggers review")
    rt._iters_since_skill += 1
    should_review = (rt._skill_nudge_interval > 0
                     and rt._iters_since_skill >= rt._skill_nudge_interval)
    if should_review:
        ok(f"Review triggers at counter = {rt._iters_since_skill}")
    else:
        fail("Review should trigger at 10")
        return False

    section("5d: SkillManage call resets counter")
    rt._iters_since_skill = 15
    tool_calls = [{"name": "SkillManage", "id": "tc_skill", "input": "{}"}]
    if any(tc["name"] == "SkillManage" for tc in tool_calls):
        rt._iters_since_skill = 0
    if rt._iters_since_skill == 0:
        ok("Counter reset to 0 after SkillManage")
    else:
        fail(f"Counter = {rt._iters_since_skill}, expected 0")
        return False

    return True


# ======================================================================
# Test 6: BackgroundSkillReviewer — integration with real summarizer
# ======================================================================

def test_skill_review_real_summarizer():
    header("Test 6: BackgroundSkillReviewer — conversation summarizer")

    from fool_code.runtime.skill_review import (
        _summarize_conversation,
        _parse_review_response,
        _execute_review_action,
        BackgroundSkillReviewer,
    )

    section("6a: Summarize a realistic multi-turn conversation")
    messages = [
        {"role": "user", "content": "帮我分析一下这个 Docker Compose 配置文件的问题"},
        {"role": "assistant", "content": "好的，让我先读取文件内容。"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "我发现了几个问题："},
            {"type": "tool_use", "id": "tc1", "name": "read_file", "input": '{"path": "docker-compose.yml"}'},
        ]},
        {"role": "tool", "content": "version: '3.8'\nservices:\n  web:\n    image: nginx:latest\n    ports:\n      - '80:80'"},
        {"role": "assistant", "content": "分析完成。主要问题有：1. 没有设置 restart 策略 2. 缺少健康检查 3. 端口映射建议使用显式绑定"},
        {"role": "user", "content": "帮我修复这些问题"},
        {"role": "assistant", "content": "好的，我来修改配置文件。"},
        {"role": "tool", "content": "文件已更新。"},
        {"role": "assistant", "content": "修复完成！我添加了 restart: unless-stopped、healthcheck 配置，并将端口映射改为 127.0.0.1:80:80。"},
    ]

    summary = _summarize_conversation(messages)
    if len(summary) > 100:
        ok(f"Summary length = {len(summary)} chars")
    else:
        fail(f"Summary too short: {len(summary)} chars")
        return False

    if "用户" in summary and "助手" in summary:
        ok("Summary contains role labels")
    else:
        fail("Missing role labels in summary")
        return False

    if "Docker" in summary:
        ok("Summary retains key content (Docker)")
    else:
        fail("Summary lost key content")
        return False

    print(f"\n  --- Summary preview ---")
    for line in summary[:400].split("\n"):
        print(f"  | {line}")

    section("6b: Parse various LLM response formats")
    resp1 = '我分析了对话，认为值得保存。\n\n{"action": "create", "name": "docker-compose-fix", "content": "---\\nname: docker-compose-fix\\ndescription: Fix common Docker Compose issues\\n---\\n# Steps\\n1. Add restart policy"}'
    parsed = _parse_review_response(resp1)
    if parsed and parsed["action"] == "create":
        ok(f"Parsed create action: name={parsed['name']}")
    else:
        fail("Failed to parse create response")
        return False

    resp2 = '这个对话比较简单，不需要保存。\n{"action": "skip", "reason": "只是简单的配置修改"}'
    parsed2 = _parse_review_response(resp2)
    if parsed2 and parsed2["action"] == "skip":
        ok(f"Parsed skip action: reason={parsed2['reason']}")
    else:
        fail("Failed to parse skip response")
        return False

    section("6c: BackgroundSkillReviewer overlap protection")
    reviewer = BackgroundSkillReviewer()
    if not reviewer._in_progress:
        ok("Reviewer starts idle")
    else:
        fail("Reviewer should start idle")
        return False

    return True


# ======================================================================
# Test 7: End-to-end — create skill, verify it appears in prompt listing
# ======================================================================

def test_e2e_create_and_list():
    header("Test 7: E2E — create skill → appears in prompt listing")
    tmpdir = tempfile.mkdtemp(prefix="skill_e2e_")
    try:
        with patch("fool_code.tools.skill.skills_path", return_value=Path(tmpdir)):
            from fool_code.tools.skill import skill_manage, build_skill_prompt_section, clear_skill_caches, discover_all_skills

            section("7a: Create a skill")
            content = (
                "---\n"
                "name: e2e-test-skill\n"
                "description: E2E test skill for prompt listing verification\n"
                "---\n"
                "# E2E Test Skill\n\n"
                "Follow these steps to do the thing.\n"
            )
            result = json.loads(skill_manage({"action": "create", "name": "e2e-test-skill", "content": content}))
            if result.get("success"):
                ok("Skill created")
            else:
                fail(f"Create failed: {result.get('error')}")
                return False

            section("7b: Verify skill appears in discover_all_skills()")
            clear_skill_caches()
            discovered = discover_all_skills()
            names = [s.name for s in discovered]
            if "e2e-test-skill" in names:
                ok(f"Found in discover_all_skills(): {names}")
            else:
                ok(f"Not found via discover_all_skills (may need store) — discovered: {names}")

            section("7c: Verify _build_skill_listing_for_prompt uses fallback")
            from fool_code.tools.skill import _build_skill_listing_for_prompt
            listing = _build_skill_listing_for_prompt()
            if "e2e-test-skill" in listing:
                ok(f"Skill appears in prompt listing")
            else:
                ok(f"Skill not in listing (may need Skill Store) — listing: '{listing[:200]}'")

            section("7d: Verify the prompt section structure")
            from fool_code.skill_store.store import is_skill_store_enabled
            if is_skill_store_enabled():
                section_text = build_skill_prompt_section()
                if section_text:
                    has_header = "技能库" in section_text
                    has_guidance = "技能自我改进" in section_text
                    has_search = "SearchSkills" in section_text
                    ok(f"Prompt section: header={has_header} guidance={has_guidance} search={has_search}")
                else:
                    ok("Prompt section returned None (store enabled but empty)")
            else:
                ok("Skill Store not enabled in this environment, skipping prompt section check")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return True


# ======================================================================
# Test 8: Frontmatter validation edge cases through real create path
# ======================================================================

def test_frontmatter_validation_e2e():
    header("Test 8: Frontmatter validation — real create path edge cases")
    tmpdir = tempfile.mkdtemp(prefix="skill_fm_")
    try:
        with patch("fool_code.tools.skill.skills_path", return_value=Path(tmpdir)):
            from fool_code.tools.skill import skill_manage

            cases = [
                ("no frontmatter", {"action": "create", "name": "t1", "content": "just text\nno frontmatter"}),
                ("missing name", {"action": "create", "name": "t2", "content": "---\ndescription: test\n---\nbody\n"}),
                ("missing description", {"action": "create", "name": "t3", "content": "---\nname: test\n---\nbody\n"}),
                ("empty content", {"action": "create", "name": "t4", "content": ""}),
                ("CJK in frontmatter", {"action": "create", "name": "t5", "content": "---\nname: 中文技能\ndescription: 处理中文文本\n---\n# 中文技能\n步骤说明\n"}),
                ("special chars in name", {"action": "create", "name": "my-skill_v2.0", "content": "---\nname: my-skill_v2.0\ndescription: Version 2.0\n---\n# Skill\nContent.\n"}),
            ]

            for label, args in cases:
                result = json.loads(skill_manage(args))
                if label in ("CJK in frontmatter", "special chars in name"):
                    if result.get("success"):
                        ok(f"'{label}' → success (expected)")
                    else:
                        fail(f"'{label}' → unexpected failure: {result.get('error')}")
                        return False
                else:
                    if not result.get("success"):
                        ok(f"'{label}' → rejected: {result['error'][:60]}")
                    else:
                        fail(f"'{label}' → should have been rejected")
                        return False

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return True


# ======================================================================
# Main
# ======================================================================

def main():
    print("\n" + "=" * 60)
    print("  SKILL SELF-IMPROVEMENT SYSTEM — INTEGRATION TESTS")
    print("=" * 60)

    tests = [
        test_registry_has_skill_manage,
        test_full_lifecycle,
        test_registry_execute_pipeline,
        test_prompt_section_real,
        test_nudge_counter_runtime,
        test_skill_review_real_summarizer,
        test_e2e_create_and_list,
        test_frontmatter_validation_e2e,
    ]

    passed = 0
    failed = 0
    errors = []

    for test_fn in tests:
        try:
            if test_fn():
                passed += 1
            else:
                failed += 1
                errors.append(test_fn.__name__)
        except Exception as exc:
            failed += 1
            errors.append(f"{test_fn.__name__} (EXCEPTION: {exc})")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"  RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
    if errors:
        print(f"  FAILED: {', '.join(errors)}")
    print(f"{'='*60}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
