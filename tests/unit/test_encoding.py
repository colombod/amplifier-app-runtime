"""Unit tests for UTF-8 encoding and cross-platform handling."""

from amplifier_app_runtime.protocol.commands import Command
from amplifier_app_runtime.protocol.events import Event


class TestUTF8Encoding:
    """Test UTF-8 encoding in protocol types."""

    def test_unicode_in_command_params(self):
        """Command should handle Unicode in params."""
        cmd = Command.prompt_send(
            session_id="sess_123",
            content="Hello 世界 🌍 Привет مرحبا",
        )

        json_bytes = cmd.model_dump_json().encode("utf-8")
        restored = Command.model_validate_json(json_bytes)

        assert restored.params["content"] == "Hello 世界 🌍 Привет مرحبا"

    def test_unicode_in_event_data(self):
        """Event should handle Unicode in data."""
        event = Event.content_delta(
            correlation_id="cmd_123",
            delta="日本語テスト 🎌",
            sequence=0,
        )

        json_bytes = event.model_dump_json().encode("utf-8")
        restored = Event.model_validate_json(json_bytes)

        assert restored.data["delta"] == "日本語テスト 🎌"

    def test_emoji_sequences(self):
        """Should handle complex emoji sequences."""
        # Family emoji (multi-codepoint)
        content = "👨‍👩‍👧‍👦 Family test"
        cmd = Command.prompt_send(session_id="s", content=content)

        json_str = cmd.model_dump_json()
        restored = Command.model_validate_json(json_str)

        assert restored.params["content"] == content

    def test_surrogate_pairs(self):
        """Should handle characters outside BMP (surrogate pairs in UTF-16)."""
        # Mathematical symbols, ancient scripts
        content = "𝔘𝔫𝔦𝔠𝔬𝔡𝔢 𝕿𝖊𝖘𝖙"
        event = Event.result("cmd_123", {"text": content})

        json_str = event.model_dump_json()
        restored = Event.model_validate_json(json_str)

        assert restored.data["text"] == content

    def test_rtl_text(self):
        """Should handle right-to-left text."""
        content = "مرحبا بالعالم"  # Arabic: Hello World
        cmd = Command.prompt_send(session_id="s", content=content)

        restored = Command.model_validate_json(cmd.model_dump_json())
        assert restored.params["content"] == content

    def test_mixed_scripts(self):
        """Should handle mixed scripts in single string."""
        content = "English 中文 العربية עברית ελληνικά"
        event = Event.content_delta("c", content, sequence=0)

        restored = Event.model_validate_json(event.model_dump_json())
        assert restored.data["delta"] == content


class TestNewlineHandling:
    """Test newline handling in JSON content."""

    def test_lf_in_content(self):
        """LF (Unix newlines) should be preserved."""
        content = "line1\nline2\nline3"
        cmd = Command.prompt_send(session_id="s", content=content)

        json_str = cmd.model_dump_json()
        assert "\\n" in json_str  # Escaped in JSON

        restored = Command.model_validate_json(json_str)
        assert restored.params["content"] == content
        assert restored.params["content"].count("\n") == 2

    def test_crlf_in_content(self):
        """CRLF (Windows newlines) should be preserved."""
        content = "line1\r\nline2\r\nline3"
        cmd = Command.prompt_send(session_id="s", content=content)

        restored = Command.model_validate_json(cmd.model_dump_json())
        assert restored.params["content"] == content
        assert "\r\n" in restored.params["content"]

    def test_mixed_newlines(self):
        """Mixed newline styles should be preserved."""
        content = "unix\nwindows\r\nold-mac\rend"
        event = Event.result("c", {"text": content})

        restored = Event.model_validate_json(event.model_dump_json())
        assert restored.data["text"] == content


class TestSpecialCharacters:
    """Test handling of special characters."""

    def test_json_special_chars(self):
        """JSON special characters should be properly escaped."""
        content = 'Quote: "hello" Backslash: \\ Tab:\there'
        cmd = Command.prompt_send(session_id="s", content=content)

        json_str = cmd.model_dump_json()
        # Should be valid JSON
        restored = Command.model_validate_json(json_str)
        assert restored.params["content"] == content

    def test_control_characters(self):
        """Control characters should be handled."""
        # Tab, form feed, backspace
        content = "tab:\there formfeed:\fhere"
        event = Event.result("c", {"text": content})

        restored = Event.model_validate_json(event.model_dump_json())
        assert restored.data["text"] == content

    def test_null_character(self):
        """Null character in string should be handled."""
        content = "before\x00after"
        cmd = Command.prompt_send(session_id="s", content=content)

        restored = Command.model_validate_json(cmd.model_dump_json())
        assert restored.params["content"] == content

    def test_unicode_escapes_in_json(self):
        """Unicode escape sequences in JSON should parse correctly."""
        # JSON with Unicode escapes
        json_str = '{"id":"c","cmd":"test","params":{"text":"Hello \\u4e16\\u754c"}}'

        cmd = Command.model_validate_json(json_str)
        assert cmd.params["text"] == "Hello 世界"


class TestBOMHandling:
    """Test UTF-8 BOM handling."""

    def test_json_without_bom(self):
        """Standard JSON without BOM should parse."""
        json_bytes = b'{"id":"c","cmd":"test","params":{}}'

        cmd = Command.model_validate_json(json_bytes)
        assert cmd.cmd == "test"

    def test_strip_bom_before_parse(self):
        """UTF-8 BOM at start should be stripped before parsing."""
        # UTF-8 BOM: EF BB BF
        json_with_bom = b'\xef\xbb\xbf{"id":"c","cmd":"test","params":{}}'

        # Note: Pydantic may or may not handle BOM - this tests the behavior
        # If it fails, we need to strip BOM in our adapter (which we do)
        json_without_bom = json_with_bom.lstrip(b"\xef\xbb\xbf")
        cmd = Command.model_validate_json(json_without_bom)
        assert cmd.cmd == "test"


class TestEdgeCases:
    """Test edge cases in encoding."""

    def test_empty_string(self):
        """Empty string should be handled."""
        cmd = Command.prompt_send(session_id="s", content="")

        restored = Command.model_validate_json(cmd.model_dump_json())
        assert restored.params["content"] == ""

    def test_whitespace_only(self):
        """Whitespace-only content should be preserved."""
        content = "   \t\n   "
        cmd = Command.prompt_send(session_id="s", content=content)

        restored = Command.model_validate_json(cmd.model_dump_json())
        assert restored.params["content"] == content

    def test_very_long_unicode_string(self):
        """Long Unicode strings should work."""
        # 10000 Unicode characters
        content = "测试" * 5000
        event = Event.result("c", {"text": content})

        restored = Event.model_validate_json(event.model_dump_json())
        assert restored.data["text"] == content
        assert len(restored.data["text"]) == 10000

    def test_deeply_nested_unicode(self):
        """Unicode in nested structures should work."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "text": "深层嵌套 🔍",
                        "list": ["项目1", "項目2", "アイテム3"],
                    }
                }
            }
        }
        event = Event.result("c", data)

        restored = Event.model_validate_json(event.model_dump_json())
        assert restored.data["level1"]["level2"]["level3"]["text"] == "深层嵌套 🔍"
        assert restored.data["level1"]["level2"]["level3"]["list"][2] == "アイテム3"


class TestStdioLineFormat:
    """Test that output format is correct for stdio transport."""

    def test_event_json_is_single_line(self):
        """Event JSON should be a single line (no pretty printing)."""
        event = Event.result(
            "cmd_123",
            {
                "multiline": "should\nstill\nbe\nsingle\nline\njson",
                "nested": {"key": "value"},
            },
        )

        json_str = event.model_dump_json()

        # Should be single line (no literal newlines in JSON structure)
        # Content newlines are escaped as \n
        assert json_str.count("\n") == 0
        assert "\\n" in json_str  # Escaped newlines in content

    def test_command_json_is_single_line(self):
        """Command JSON should be a single line."""
        cmd = Command.prompt_send(
            session_id="s",
            content="multi\nline\ncontent",
        )

        json_str = cmd.model_dump_json()
        assert json_str.count("\n") == 0
