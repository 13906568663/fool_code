"""Skill self-improvement system test suite.

Covers:
  - skill_manage create / patch / delete
  - Frontmatter validation
  - build_skill_prompt_section with guidance + listing
  - Nudge counter logic in ConversationRuntime
  - Background skill review conversation summarizer + response parser

Run:  uv run python -m pytest tests/test_skill_manage.py -v
  or: uv run python tests/test_skill_manage.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ======================================================================
# Phase 1: skill_manage — create / patch / delete
# ======================================================================

class TestSkillManageCreate:
    """Test SkillManage(action='create')."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp(prefix="skill_test_")
        self._patcher = patch(
            "fool_code.tools.skill.skills_path",
            return_value=Path(self._tmpdir),
        )
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_create_success(self):
        from fool_code.tools.skill import skill_manage

        content = (
            "---\nname: test-skill\ndescription: A test skill\n---\n"
            "# Test Skill\nDo something useful."
        )
        result = json.loads(skill_manage({
            "action": "create",
            "name": "test-skill",
            "content": content,
        }))
        assert result["success"] is True
        assert result["action"] == "create"
        assert result["name"] == "test-skill"

        skill_md = Path(self._tmpdir) / "test-skill" / "SKILL.md"
        assert skill_md.exists()
        assert skill_md.read_text(encoding="utf-8") == content

    def test_create_with_category(self):
        """Category param is accepted but directory is flat (no nesting)."""
        from fool_code.tools.skill import skill_manage

        content = (
            "---\nname: db-helper\ndescription: DB skill\n---\n"
            "# DB Helper\nHelp with databases."
        )
        result = json.loads(skill_manage({
            "action": "create",
            "name": "db-helper",
            "content": content,
            "category": "database",
        }))
        assert result["success"] is True

        # Flat layout: skills/db-helper/SKILL.md (not skills/database/db-helper/)
        skill_md = Path(self._tmpdir) / "db-helper" / "SKILL.md"
        assert skill_md.exists()

    def test_create_duplicate_fails(self):
        from fool_code.tools.skill import skill_manage

        content = (
            "---\nname: dup-skill\ndescription: Duplicate test\n---\n"
            "# Dup\nContent."
        )
        skill_manage({"action": "create", "name": "dup-skill", "content": content})

        result = json.loads(skill_manage({
            "action": "create",
            "name": "dup-skill",
            "content": content,
        }))
        assert result["success"] is False
        assert "已存在" in result["error"]

    def test_create_missing_name_in_frontmatter(self):
        from fool_code.tools.skill import skill_manage

        content = "---\ndescription: No name field\n---\nBody text."
        result = json.loads(skill_manage({
            "action": "create",
            "name": "no-name",
            "content": content,
        }))
        assert result["success"] is False
        assert "name" in result["error"]

    def test_create_missing_description_in_frontmatter(self):
        from fool_code.tools.skill import skill_manage

        content = "---\nname: no-desc\n---\nBody text."
        result = json.loads(skill_manage({
            "action": "create",
            "name": "no-desc",
            "content": content,
        }))
        assert result["success"] is False
        assert "description" in result["error"]

    def test_create_no_frontmatter(self):
        from fool_code.tools.skill import skill_manage

        content = "# Just a title\nNo frontmatter here."
        result = json.loads(skill_manage({
            "action": "create",
            "name": "no-fm",
            "content": content,
        }))
        assert result["success"] is False
        assert "frontmatter" in result["error"]

    def test_create_empty_body(self):
        from fool_code.tools.skill import skill_manage

        content = "---\nname: empty-body\ndescription: Empty\n---\n   \n"
        result = json.loads(skill_manage({
            "action": "create",
            "name": "empty-body",
            "content": content,
        }))
        assert result["success"] is False
        assert "正文" in result["error"]

    def test_create_empty_content(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({
            "action": "create",
            "name": "empty",
            "content": "",
        }))
        assert result["success"] is False

    def test_create_empty_name(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({
            "action": "create",
            "name": "",
            "content": "something",
        }))
        assert result["success"] is False
        assert "name" in result["error"]


class TestSkillManagePatch:
    """Test SkillManage(action='patch')."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp(prefix="skill_test_")
        self._patcher = patch(
            "fool_code.tools.skill.skills_path",
            return_value=Path(self._tmpdir),
        )
        self._patcher.start()
        self._create_skill("patch-target", (
            "---\nname: patch-target\ndescription: Before patch\n---\n"
            "# Patch Target\nOld content here."
        ))

    def teardown_method(self):
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _create_skill(self, name: str, content: str):
        skill_dir = Path(self._tmpdir) / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    def test_patch_success(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({
            "action": "patch",
            "name": "patch-target",
            "old_string": "Old content here.",
            "new_string": "New content here.",
        }))
        assert result["success"] is True
        assert result["action"] == "patch"

        skill_md = Path(self._tmpdir) / "patch-target" / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        assert "New content here." in text
        assert "Old content here." not in text

    def test_patch_not_found_skill(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({
            "action": "patch",
            "name": "nonexistent",
            "old_string": "x",
            "new_string": "y",
        }))
        assert result["success"] is False
        assert "未找到" in result["error"]

    def test_patch_old_string_not_found(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({
            "action": "patch",
            "name": "patch-target",
            "old_string": "DOES NOT EXIST IN FILE",
            "new_string": "replacement",
        }))
        assert result["success"] is False
        assert "old_string" in result["error"]

    def test_patch_breaks_frontmatter(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({
            "action": "patch",
            "name": "patch-target",
            "old_string": "name: patch-target",
            "new_string": "title: patch-target",
        }))
        assert result["success"] is False
        assert "name" in result["error"]

    def test_patch_missing_old_string_param(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({
            "action": "patch",
            "name": "patch-target",
        }))
        assert result["success"] is False


class TestSkillManageDelete:
    """Test SkillManage(action='delete')."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp(prefix="skill_test_")
        self._patcher = patch(
            "fool_code.tools.skill.skills_path",
            return_value=Path(self._tmpdir),
        )
        self._patcher.start()
        skill_dir = Path(self._tmpdir) / "delete-me"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: delete-me\ndescription: To be deleted\n---\n# Del\nContent.",
            encoding="utf-8",
        )

    def teardown_method(self):
        self._patcher.stop()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_delete_success(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({"action": "delete", "name": "delete-me"}))
        assert result["success"] is True
        assert result["action"] == "delete"

        assert not (Path(self._tmpdir) / "delete-me").exists()

    def test_delete_not_found(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({"action": "delete", "name": "nope"}))
        assert result["success"] is False
        assert "未找到" in result["error"]


class TestSkillManageEdgeCases:
    """Test edge cases for skill_manage."""

    def test_unknown_action(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({"action": "unknown", "name": "x"}))
        assert result["success"] is False
        assert "未知 action" in result["error"]

    def test_missing_action(self):
        from fool_code.tools.skill import skill_manage

        result = json.loads(skill_manage({"name": "x"}))
        assert result["success"] is False
        assert "action" in result["error"]


# ======================================================================
# Phase 2: build_skill_prompt_section — guidance + listing
# ======================================================================

class TestSkillPromptSection:
    """Test that the system prompt section includes guidance and skill listing."""

    @patch("fool_code.skill_store.store.is_skill_store_enabled", return_value=True)
    @patch("fool_code.skill_store.store.get_store")
    def test_prompt_contains_guidance(self, mock_store_fn, mock_enabled):
        from fool_code.tools.skill import build_skill_prompt_section

        mock_store = MagicMock()
        mock_store.list_skills.return_value = "[]"
        mock_store_fn.return_value = mock_store

        section = build_skill_prompt_section()
        assert section is not None
        assert "技能自我改进" in section
        assert "SkillManage" in section
        assert "create" in section
        assert "patch" in section

    @patch("fool_code.skill_store.store.is_skill_store_enabled", return_value=True)
    @patch("fool_code.skill_store.store.get_store")
    def test_prompt_lists_skills(self, mock_store_fn, mock_enabled):
        from fool_code.tools.skill import build_skill_prompt_section

        mock_store = MagicMock()
        mock_store.list_skills.return_value = json.dumps([
            {"id": "excel-handler", "description": "处理 Excel 文件", "display_name": "Excel Handler"},
            {"id": "git-workflow", "description": "Git 工作流自动化", "display_name": "Git Workflow"},
        ])
        mock_store_fn.return_value = mock_store

        section = build_skill_prompt_section()
        assert section is not None
        assert "excel-handler" in section
        assert "git-workflow" in section
        assert "已有技能" in section

    @patch("fool_code.skill_store.store.is_skill_store_enabled", return_value=False)
    def test_prompt_returns_none_when_disabled(self, mock_enabled):
        from fool_code.tools.skill import build_skill_prompt_section

        section = build_skill_prompt_section()
        assert section is None


# ======================================================================
# Phase 3: Nudge counter logic
# ======================================================================

class TestNudgeCounter:
    """Test the iteration counter and SkillManage reset in ConversationRuntime."""

    def test_counter_initializes_to_zero(self):
        rt = self._make_runtime()
        assert rt._iters_since_skill == 0
        assert rt._skill_nudge_interval == 10

    def test_counter_increments_on_non_skill_tool_calls(self):
        rt = self._make_runtime()

        for i in range(5):
            rt._iters_since_skill += 1
        assert rt._iters_since_skill == 5

    def test_counter_resets_on_skill_manage(self):
        rt = self._make_runtime()
        rt._iters_since_skill = 8

        tool_calls = [{"name": "SkillManage", "id": "tc1", "input": "{}"}]
        if any(tc["name"] == "SkillManage" for tc in tool_calls):
            rt._iters_since_skill = 0

        assert rt._iters_since_skill == 0

    def test_counter_does_not_reset_on_other_tools(self):
        rt = self._make_runtime()
        rt._iters_since_skill = 8

        tool_calls = [{"name": "bash", "id": "tc1", "input": "{}"}]
        if any(tc["name"] == "SkillManage" for tc in tool_calls):
            rt._iters_since_skill = 0

        assert rt._iters_since_skill == 8

    def test_review_trigger_threshold(self):
        rt = self._make_runtime()
        rt._iters_since_skill = 10

        should_review = (
            rt._skill_nudge_interval > 0
            and rt._iters_since_skill >= rt._skill_nudge_interval
        )
        assert should_review is True

    def test_no_review_below_threshold(self):
        rt = self._make_runtime()
        rt._iters_since_skill = 9

        should_review = (
            rt._skill_nudge_interval > 0
            and rt._iters_since_skill >= rt._skill_nudge_interval
        )
        assert should_review is False

    def test_no_review_when_interval_zero(self):
        rt = self._make_runtime()
        rt._skill_nudge_interval = 0
        rt._iters_since_skill = 100

        should_review = (
            rt._skill_nudge_interval > 0
            and rt._iters_since_skill >= rt._skill_nudge_interval
        )
        assert should_review is False

    @staticmethod
    def _make_runtime():
        """Create a minimal ConversationRuntime with mocked dependencies."""
        from fool_code.types import Session
        from fool_code.runtime.conversation import ConversationRuntime

        session = Session()
        mock_provider = MagicMock()
        mock_registry = MagicMock()
        mock_registry.definitions_filtered.return_value = []
        mock_gate = MagicMock()
        mock_event_cb = MagicMock()

        return ConversationRuntime(
            session=session,
            provider=mock_provider,
            tool_registry=mock_registry,
            system_prompt=["test"],
            permission_gate=mock_gate,
            event_callback=mock_event_cb,
        )


# ======================================================================
# Phase 4: Background skill review — unit tests
# ======================================================================

class TestSkillReviewHelpers:
    """Test the background review helper functions."""

    def test_summarize_conversation_basic(self):
        from fool_code.runtime.skill_review import _summarize_conversation

        messages = [
            {"role": "user", "content": "帮我处理一下 Excel 文件"},
            {"role": "assistant", "content": "好的，我来帮你处理。"},
            {"role": "tool", "content": "文件已读取，共 100 行。"},
        ]
        summary = _summarize_conversation(messages)
        assert "用户" in summary
        assert "助手" in summary
        assert "工具结果" in summary

    def test_summarize_conversation_respects_budget(self):
        from fool_code.runtime.skill_review import _summarize_conversation, _MAX_CONVERSATION_CHARS

        long_content = "x" * 10000
        messages = [
            {"role": "user", "content": long_content},
            {"role": "assistant", "content": long_content},
        ]
        summary = _summarize_conversation(messages)
        assert len(summary) <= _MAX_CONVERSATION_CHARS + 500  # some overhead for labels

    def test_summarize_conversation_handles_block_content(self):
        from fool_code.runtime.skill_review import _summarize_conversation

        messages = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "这是一段文本"},
                {"type": "tool_use", "id": "t1"},
            ]},
        ]
        summary = _summarize_conversation(messages)
        assert "这是一段文本" in summary

    def test_parse_review_response_valid(self):
        from fool_code.runtime.skill_review import _parse_review_response

        text = '根据对话分析：\n{"action": "skip", "reason": "太简单了"}'
        result = _parse_review_response(text)
        assert result is not None
        assert result["action"] == "skip"

    def test_parse_review_response_create(self):
        from fool_code.runtime.skill_review import _parse_review_response

        text = '{"action": "create", "name": "new-skill", "content": "---\\nname: x\\n---\\nbody"}'
        result = _parse_review_response(text)
        assert result is not None
        assert result["action"] == "create"
        assert result["name"] == "new-skill"

    def test_parse_review_response_invalid(self):
        from fool_code.runtime.skill_review import _parse_review_response

        result = _parse_review_response("no json here at all")
        assert result is None

    def test_parse_review_response_malformed_json(self):
        from fool_code.runtime.skill_review import _parse_review_response

        result = _parse_review_response("{not valid json}")
        assert result is None


# ======================================================================
# Phase 5: Frontmatter validation edge cases
# ======================================================================

class TestFrontmatterValidation:
    """Test _validate_skill_content directly."""

    def test_valid_content(self):
        from fool_code.tools.skill import _validate_skill_content

        content = "---\nname: test\ndescription: Test desc\n---\n# Test\nBody."
        assert _validate_skill_content(content) is None

    def test_no_frontmatter(self):
        from fool_code.tools.skill import _validate_skill_content

        assert _validate_skill_content("Just text") is not None

    def test_no_name(self):
        from fool_code.tools.skill import _validate_skill_content

        content = "---\ndescription: desc\n---\nBody."
        err = _validate_skill_content(content)
        assert err is not None
        assert "name" in err

    def test_no_description(self):
        from fool_code.tools.skill import _validate_skill_content

        content = "---\nname: test\n---\nBody."
        err = _validate_skill_content(content)
        assert err is not None
        assert "description" in err

    def test_empty_body(self):
        from fool_code.tools.skill import _validate_skill_content

        content = "---\nname: test\ndescription: desc\n---\n  \n  "
        err = _validate_skill_content(content)
        assert err is not None
        assert "正文" in err

    def test_quoted_values(self):
        from fool_code.tools.skill import _validate_skill_content

        content = '---\nname: "my-skill"\ndescription: "A skill"\n---\n# Body\nContent.'
        assert _validate_skill_content(content) is None


# ======================================================================
# Main entry
# ======================================================================

if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
