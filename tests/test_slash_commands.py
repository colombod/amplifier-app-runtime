"""Tests for ACP slash commands functionality."""

import pytest

from amplifier_app_runtime.acp.slash_commands import (
    ParsedCommand,
    SlashCommandHandler,
    SlashCommandRegistry,
    SlashCommandResult,
    create_available_commands_update,
    is_slash_command,
    parse_slash_command,
)

# =============================================================================
# Command Parsing Tests
# =============================================================================


class TestParseSlashCommand:
    """Tests for slash command parsing."""

    def test_parse_simple_command(self) -> None:
        """Parse command without arguments."""
        result = parse_slash_command("/help")
        assert result is not None
        assert result.name == "help"
        assert result.args == ""
        assert result.raw == "/help"

    def test_parse_command_with_args(self) -> None:
        """Parse command with arguments."""
        result = parse_slash_command("/mode plan")
        assert result is not None
        assert result.name == "mode"
        assert result.args == "plan"
        assert result.raw == "/mode plan"

    def test_parse_command_with_multiple_args(self) -> None:
        """Parse command with multiple arguments."""
        result = parse_slash_command("/recipe run my-recipe.yaml")
        assert result is not None
        assert result.name == "recipe"
        assert result.args == "run my-recipe.yaml"

    def test_parse_non_command(self) -> None:
        """Non-command text returns None."""
        assert parse_slash_command("hello world") is None
        assert parse_slash_command("") is None
        assert parse_slash_command("  ") is None

    def test_parse_command_case_insensitive(self) -> None:
        """Command names are normalized to lowercase."""
        result = parse_slash_command("/HELP")
        assert result is not None
        assert result.name == "help"

    def test_parse_command_with_whitespace(self) -> None:
        """Leading/trailing whitespace is handled."""
        result = parse_slash_command("  /help  ")
        assert result is not None
        assert result.name == "help"

    def test_is_slash_command(self) -> None:
        """Test is_slash_command helper."""
        assert is_slash_command("/help") is True
        assert is_slash_command("/mode plan") is True
        assert is_slash_command("hello") is False
        assert is_slash_command("") is False


# =============================================================================
# Command Registry Tests
# =============================================================================


class TestSlashCommandRegistry:
    """Tests for command registry."""

    def test_get_all_commands(self) -> None:
        """Get all available commands."""
        commands = SlashCommandRegistry.get_all_commands()
        assert len(commands) > 0

        # Check essential commands are present
        names = [c.name for c in commands]
        assert "help" in names
        assert "tools" in names
        assert "agents" in names
        assert "status" in names
        assert "mode" in names
        assert "modes" in names

    def test_tier1_commands_always_present(self) -> None:
        """Tier 1 commands are always available."""
        commands = SlashCommandRegistry.get_commands_for_session(None)
        names = [c.name for c in commands]

        for cmd in SlashCommandRegistry.TIER1_COMMANDS:
            assert cmd.name in names

    def test_commands_have_descriptions(self) -> None:
        """All commands have descriptions."""
        for cmd in SlashCommandRegistry.get_all_commands():
            assert cmd.description
            assert len(cmd.description) > 10

    def test_mode_command_has_input(self) -> None:
        """Mode command has input specification."""
        commands = SlashCommandRegistry.get_all_commands()
        mode_cmd = next(c for c in commands if c.name == "mode")
        assert mode_cmd.input is not None
        assert mode_cmd.input.root is not None
        assert mode_cmd.input.root.hint


# =============================================================================
# Command Handler Tests
# =============================================================================


class MockSession:
    """Mock session for testing slash commands."""

    def __init__(self) -> None:
        self.session_id = "test-session-123"
        self._coordinator = MockCoordinator()
        self._context_cleared = False

    def list_tools(self) -> list[dict]:
        return [
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
            {"name": "bash", "description": "Execute shell commands"},
        ]

    async def clear_context(self) -> None:
        self._context_cleared = True


class MockCoordinator:
    """Mock coordinator for testing."""

    def __init__(self) -> None:
        self.config = {
            "bundle": "test-bundle",
            "providers": {"anthropic": {}, "openai": {}},
            "tools": [1, 2, 3],  # Just counts
            "agents": {
                "zen-architect": {"description": "System design"},
                "bug-hunter": {"description": "Debugging"},
            },
            "hooks": [1, 2],
        }


class TestSlashCommandHandler:
    """Tests for command execution."""

    @pytest.fixture
    def handler(self) -> SlashCommandHandler:
        """Create handler with mock session."""
        return SlashCommandHandler(MockSession())  # type: ignore

    @pytest.mark.asyncio
    async def test_help_command(self, handler: SlashCommandHandler) -> None:
        """Help command lists available commands."""
        cmd = ParsedCommand(name="help", args="", raw="/help")
        result = await handler.execute(cmd)

        assert result.success
        assert "Available Slash Commands" in result.message
        assert "/help" in result.message
        assert "/mode" in result.message

    @pytest.mark.asyncio
    async def test_tools_command(self, handler: SlashCommandHandler) -> None:
        """Tools command lists available tools."""
        cmd = ParsedCommand(name="tools", args="", raw="/tools")
        result = await handler.execute(cmd)

        assert result.success
        assert "Available Tools" in result.message
        assert "read_file" in result.message
        assert "bash" in result.message

    @pytest.mark.asyncio
    async def test_agents_command(self, handler: SlashCommandHandler) -> None:
        """Agents command lists available agents."""
        cmd = ParsedCommand(name="agents", args="", raw="/agents")
        result = await handler.execute(cmd)

        assert result.success
        assert "Available Agents" in result.message
        assert "zen-architect" in result.message
        assert "bug-hunter" in result.message

    @pytest.mark.asyncio
    async def test_status_command(self, handler: SlashCommandHandler) -> None:
        """Status command shows session info."""
        cmd = ParsedCommand(name="status", args="", raw="/status")
        result = await handler.execute(cmd)

        assert result.success
        assert "Session Status" in result.message
        assert "test-session-123" in result.message
        assert "test-bundle" in result.message

    @pytest.mark.asyncio
    async def test_clear_command(self, handler: SlashCommandHandler) -> None:
        """Clear command clears context."""
        cmd = ParsedCommand(name="clear", args="", raw="/clear")
        result = await handler.execute(cmd)

        assert result.success
        assert "cleared" in result.message.lower()
        assert handler._session._context_cleared  # type: ignore

    @pytest.mark.asyncio
    async def test_mode_activate(self, handler: SlashCommandHandler) -> None:
        """Mode command activates a mode."""
        cmd = ParsedCommand(name="mode", args="plan", raw="/mode plan")
        result = await handler.execute(cmd)

        assert result.success
        assert "plan" in result.message
        assert "activated" in result.message
        assert handler._active_mode == "plan"
        assert result.update_commands  # Should trigger command update

    @pytest.mark.asyncio
    async def test_mode_deactivate(self, handler: SlashCommandHandler) -> None:
        """Mode off deactivates current mode."""
        # First activate
        handler._active_mode = "plan"

        cmd = ParsedCommand(name="mode", args="off", raw="/mode off")
        result = await handler.execute(cmd)

        assert result.success
        assert "deactivated" in result.message
        assert handler._active_mode is None

    @pytest.mark.asyncio
    async def test_mode_shortcut_plan(self, handler: SlashCommandHandler) -> None:
        """/plan is shortcut for /mode plan."""
        cmd = ParsedCommand(name="plan", args="", raw="/plan")
        result = await handler.execute(cmd)

        assert result.success
        assert handler._active_mode == "plan"

    @pytest.mark.asyncio
    async def test_mode_shortcut_explore(self, handler: SlashCommandHandler) -> None:
        """/explore is shortcut for /mode explore."""
        cmd = ParsedCommand(name="explore", args="", raw="/explore")
        result = await handler.execute(cmd)

        assert result.success
        assert handler._active_mode == "explore"

    @pytest.mark.asyncio
    async def test_modes_command(self, handler: SlashCommandHandler) -> None:
        """Modes command lists available modes."""
        cmd = ParsedCommand(name="modes", args="", raw="/modes")
        result = await handler.execute(cmd)

        assert result.success
        assert "Available Modes" in result.message
        assert "plan" in result.message
        assert "explore" in result.message
        assert "careful" in result.message

    @pytest.mark.asyncio
    async def test_config_command(self, handler: SlashCommandHandler) -> None:
        """Config command shows configuration."""
        cmd = ParsedCommand(name="config", args="", raw="/config")
        result = await handler.execute(cmd)

        assert result.success
        assert "Configuration" in result.message
        assert "test-bundle" in result.message
        assert "anthropic" in result.message

    @pytest.mark.asyncio
    async def test_unknown_command(self, handler: SlashCommandHandler) -> None:
        """Unknown command returns error."""
        cmd = ParsedCommand(name="unknown", args="", raw="/unknown")
        result = await handler.execute(cmd)

        assert not result.success
        assert "Unknown command" in result.message

    @pytest.mark.asyncio
    async def test_recipe_help(self, handler: SlashCommandHandler) -> None:
        """Recipe without args shows help."""
        cmd = ParsedCommand(name="recipe", args="", raw="/recipe")
        result = await handler.execute(cmd)

        assert result.success
        assert "Recipe Commands" in result.message
        assert "/recipe run" in result.message
        assert "/recipe list" in result.message


# =============================================================================
# ACP Integration Tests
# =============================================================================


class TestAcpIntegration:
    """Tests for ACP protocol integration."""

    def test_create_available_commands_update(self) -> None:
        """Create ACP AvailableCommandsUpdate notification."""
        update = create_available_commands_update(None)

        assert update.session_update == "available_commands_update"
        assert update.available_commands is not None
        assert len(update.available_commands) > 0

    def test_available_commands_serialization(self) -> None:
        """Commands serialize to correct JSON format."""
        update = create_available_commands_update(None)
        data = update.model_dump(by_alias=True, exclude_none=True)

        assert data["sessionUpdate"] == "available_commands_update"
        assert "availableCommands" in data

        # Check command structure
        cmd = data["availableCommands"][0]
        assert "name" in cmd
        assert "description" in cmd


# =============================================================================
# SlashCommandResult Tests
# =============================================================================


class TestSlashCommandResult:
    """Tests for SlashCommandResult dataclass."""

    def test_default_values(self) -> None:
        """Result has correct defaults."""
        result = SlashCommandResult(success=True, message="Test")

        assert result.success is True
        assert result.message == "Test"
        assert result.data == {}
        assert result.send_as_message is True
        assert result.update_commands is False

    def test_with_data(self) -> None:
        """Result can include data."""
        result = SlashCommandResult(
            success=True,
            message="Test",
            data={"key": "value"},
        )

        assert result.data == {"key": "value"}

    def test_update_commands_flag(self) -> None:
        """Result can signal command update needed."""
        result = SlashCommandResult(
            success=True,
            message="Mode changed",
            update_commands=True,
        )

        assert result.update_commands is True
