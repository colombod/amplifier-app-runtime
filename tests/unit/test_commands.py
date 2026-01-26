"""Unit tests for Command protocol type."""

import json

import pytest

from amplifier_server_app.protocol.commands import Command, CommandType


class TestCommandCreation:
    """Test Command creation and basic properties."""

    def test_create_with_defaults(self):
        """Command should generate ID automatically."""
        cmd = Command(cmd="test.command")

        assert cmd.cmd == "test.command"
        assert cmd.id.startswith("cmd_")
        assert len(cmd.id) == 16  # "cmd_" + 12 hex chars
        assert cmd.params == {}

    def test_create_with_explicit_id(self):
        """Command should accept explicit ID."""
        cmd = Command(id="my-custom-id", cmd="test.command")

        assert cmd.id == "my-custom-id"

    def test_create_with_params(self):
        """Command should store params."""
        cmd = Command(
            cmd="session.create",
            params={"bundle": "amplifier-dev", "model": "claude-sonnet"},
        )

        assert cmd.params["bundle"] == "amplifier-dev"
        assert cmd.params["model"] == "claude-sonnet"

    def test_create_factory_method(self):
        """Command.create() factory should work."""
        cmd = Command.create(
            CommandType.SESSION_CREATE,
            {"bundle": "test-bundle"},
        )

        assert cmd.cmd == "session.create"
        assert cmd.params["bundle"] == "test-bundle"

    def test_create_factory_with_string_cmd(self):
        """Command.create() should accept string command."""
        cmd = Command.create("custom.command", {"key": "value"})

        assert cmd.cmd == "custom.command"


class TestCommandFactoryMethods:
    """Test convenience factory methods."""

    def test_session_create(self):
        """session_create() should build correct command."""
        cmd = Command.session_create(
            bundle="my-bundle",
            provider="anthropic",
            model="claude-sonnet",
            working_directory="/tmp/work",
        )

        assert cmd.cmd == "session.create"
        assert cmd.params["bundle"] == "my-bundle"
        assert cmd.params["provider"] == "anthropic"
        assert cmd.params["model"] == "claude-sonnet"
        assert cmd.params["working_directory"] == "/tmp/work"

    def test_session_create_minimal(self):
        """session_create() with no args should have empty params."""
        cmd = Command.session_create()

        assert cmd.cmd == "session.create"
        assert cmd.params == {}

    def test_prompt_send(self):
        """prompt_send() should build correct command."""
        cmd = Command.prompt_send(
            session_id="sess_123",
            content="Hello, world!",
            stream=True,
        )

        assert cmd.cmd == "prompt.send"
        assert cmd.params["session_id"] == "sess_123"
        assert cmd.params["content"] == "Hello, world!"
        assert cmd.params["stream"] is True

    def test_approval_respond(self):
        """approval_respond() should build correct command."""
        cmd = Command.approval_respond(
            session_id="sess_123",
            request_id="req_456",
            choice="yes",
        )

        assert cmd.cmd == "approval.respond"
        assert cmd.params["session_id"] == "sess_123"
        assert cmd.params["request_id"] == "req_456"
        assert cmd.params["choice"] == "yes"

    def test_ping(self):
        """ping() should create ping command."""
        cmd = Command.ping()

        assert cmd.cmd == "ping"
        assert cmd.params == {}


class TestCommandParamAccess:
    """Test parameter access methods."""

    def test_get_param_existing(self):
        """get_param() should return existing param."""
        cmd = Command(cmd="test", params={"key": "value"})

        assert cmd.get_param("key") == "value"

    def test_get_param_missing_with_default(self):
        """get_param() should return default for missing param."""
        cmd = Command(cmd="test", params={})

        assert cmd.get_param("missing", "default") == "default"

    def test_get_param_missing_no_default(self):
        """get_param() should return None for missing param without default."""
        cmd = Command(cmd="test", params={})

        assert cmd.get_param("missing") is None

    def test_require_param_existing(self):
        """require_param() should return existing param."""
        cmd = Command(cmd="test", params={"key": "value"})

        assert cmd.require_param("key") == "value"

    def test_require_param_missing_raises(self):
        """require_param() should raise for missing param."""
        cmd = Command(cmd="test", params={})

        with pytest.raises(ValueError, match="Missing required parameter: key"):
            cmd.require_param("key")


class TestCommandSerialization:
    """Test JSON serialization/deserialization."""

    def test_serialize_to_json(self):
        """Command should serialize to JSON."""
        cmd = Command(
            id="cmd_test123",
            cmd="session.create",
            params={"bundle": "test"},
        )

        json_str = cmd.model_dump_json()
        data = json.loads(json_str)

        assert data["id"] == "cmd_test123"
        assert data["cmd"] == "session.create"
        assert data["params"]["bundle"] == "test"

    def test_deserialize_from_json(self):
        """Command should deserialize from JSON."""
        json_str = '{"id": "cmd_abc", "cmd": "ping", "params": {}}'

        cmd = Command.model_validate_json(json_str)

        assert cmd.id == "cmd_abc"
        assert cmd.cmd == "ping"
        assert cmd.params == {}

    def test_deserialize_from_bytes(self):
        """Command should deserialize from UTF-8 bytes."""
        json_bytes = b'{"id": "cmd_utf8", "cmd": "test", "params": {"msg": "Hello \\u4e16\\u754c"}}'

        cmd = Command.model_validate_json(json_bytes)

        assert cmd.id == "cmd_utf8"
        assert cmd.params["msg"] == "Hello 世界"

    def test_roundtrip_with_unicode(self):
        """Command should roundtrip with Unicode content."""
        original = Command(
            id="cmd_unicode",
            cmd="prompt.send",
            params={"content": "Hello 世界 🌍 مرحبا"},
        )

        json_str = original.model_dump_json()
        restored = Command.model_validate_json(json_str)

        assert restored.id == original.id
        assert restored.cmd == original.cmd
        assert restored.params["content"] == "Hello 世界 🌍 مرحبا"


class TestCommandTypes:
    """Test CommandType enum."""

    def test_all_command_types_are_strings(self):
        """All CommandType values should be valid strings."""
        for cmd_type in CommandType:
            assert isinstance(cmd_type.value, str)
            assert len(cmd_type.value) > 0  # All commands are non-empty strings

    def test_expected_command_types_exist(self):
        """Expected command types should be defined."""
        expected = [
            "session.create",
            "session.get",
            "session.list",
            "session.delete",
            "prompt.send",
            "prompt.cancel",
            "approval.respond",
            "ping",
            "capabilities",
        ]

        values = [ct.value for ct in CommandType]
        for exp in expected:
            assert exp in values, f"Missing command type: {exp}"
