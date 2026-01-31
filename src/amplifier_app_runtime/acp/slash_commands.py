"""ACP Slash Commands for Amplifier.

This module implements the ACP slash commands protocol, mapping IDE slash commands
to Amplifier operations like modes, skills, tools listing, and session management.

ACP Protocol Flow:
1. After session creation, agent sends `available_commands_update` notification
2. Client displays commands in UI (autocomplete, command palette)
3. User types `/command args` in prompt
4. Agent detects prefix, routes to handler instead of LLM
5. Handler executes and returns result
6. Agent may send dynamic command updates (e.g., after mode change)

Architecture:
- SlashCommandRegistry: Defines available commands with metadata
- SlashCommandHandler: Executes commands against Amplifier session
- Integration point: AmplifierAgentSession.execute_prompt() checks for slash prefix
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from acp.schema import (  # type: ignore[import-untyped]
    AvailableCommand,
    AvailableCommandInput,
    AvailableCommandsUpdate,
)

# Note: We use Any for session type because we access attributes via duck typing
# (hasattr checks). Any doesn't expose these attributes in its type hints.

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class SlashCommandResult:
    """Result of executing a slash command.

    Slash commands can either:
    1. Return a direct message (send_as_message=True, execute_as_prompt=None)
    2. Translate to an Amplifier prompt for full orchestration (execute_as_prompt set)

    When execute_as_prompt is set, the ACP agent should execute that prompt
    through Amplifier's normal flow, ensuring proper context, capabilities,
    and tool orchestration. This is the correct pattern for commands that
    need to invoke Amplifier tools like recipes.
    """

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    # If true, send message to client (for direct responses)
    send_as_message: bool = True
    # If set, send updated commands list after this command
    update_commands: bool = False
    # If set, execute this prompt through Amplifier instead of direct response
    # This ensures proper orchestration, context, and tool invocation
    execute_as_prompt: str | None = None


@dataclass
class ParsedCommand:
    """A parsed slash command from user input."""

    name: str
    args: str
    raw: str


# =============================================================================
# Command Registry
# =============================================================================


class SlashCommandRegistry:
    """Registry of available slash commands.

    Commands are organized in tiers:
    - Tier 1: Essential (always available)
    - Tier 2: Power features (may require specific bundles)
    - Tier 3: Workflow orchestration (requires recipes bundle)
    """

    # Tier 1: Essential commands
    TIER1_COMMANDS = [
        AvailableCommand(
            name="help",
            description="Show available slash commands",
        ),
        AvailableCommand(
            name="tools",
            description="List available tools with descriptions",
        ),
        AvailableCommand(
            name="agents",
            description="List available agents for delegation",
        ),
        AvailableCommand(
            name="status",
            description="Show session status (ID, bundle, provider, active mode)",
        ),
        AvailableCommand(
            name="clear",
            description="Clear conversation context",
        ),
        AvailableCommand(
            name="mode",
            description="Activate or deactivate a mode (e.g., /mode plan, /mode off)",
            input=AvailableCommandInput(hint="mode name or 'off'"),
        ),
        AvailableCommand(
            name="modes",
            description="List available modes",
        ),
    ]

    # Tier 2: Mode shortcuts and skills
    TIER2_COMMANDS = [
        AvailableCommand(
            name="plan",
            description="Enter plan mode (read-only analysis, no modifications)",
        ),
        AvailableCommand(
            name="explore",
            description="Enter explore mode (zero-footprint codebase exploration)",
        ),
        AvailableCommand(
            name="careful",
            description="Enter careful mode (confirmation required for destructive actions)",
        ),
        AvailableCommand(
            name="skills",
            description="List available skills",
        ),
        AvailableCommand(
            name="skill",
            description="Load a skill by name",
            input=AvailableCommandInput(hint="skill name"),
        ),
        AvailableCommand(
            name="config",
            description="Show current configuration",
        ),
    ]

    # Tier 3: Recipe commands (require recipes bundle)
    TIER3_COMMANDS = [
        AvailableCommand(
            name="recipe",
            description="Execute or manage recipes (run, list, resume, approve, cancel)",
            input=AvailableCommandInput(hint="subcommand and arguments"),
        ),
    ]

    @classmethod
    def get_all_commands(cls) -> list[AvailableCommand]:
        """Get all available commands."""
        return cls.TIER1_COMMANDS + cls.TIER2_COMMANDS + cls.TIER3_COMMANDS

    @classmethod
    def get_commands_for_session(
        cls,
        session: Any | None = None,
    ) -> list[AvailableCommand]:
        """Get commands available for a specific session.

        May filter based on session capabilities (e.g., hide recipe commands
        if recipes bundle not loaded).
        """
        commands = list(cls.TIER1_COMMANDS) + list(cls.TIER2_COMMANDS)

        # Add recipe commands if recipes tool is available
        if session:
            try:
                tools = session.list_tools() if hasattr(session, "list_tools") else []
                tool_names = [
                    t.get("name", "") if isinstance(t, dict) else getattr(t, "name", "")
                    for t in tools
                ]
                if "recipes" in tool_names:
                    commands.extend(cls.TIER3_COMMANDS)
            except Exception:
                pass  # If we can't check, include all commands

        return commands


# =============================================================================
# Command Parser
# =============================================================================


def parse_slash_command(text: str) -> ParsedCommand | None:
    """Parse a slash command from user input.

    Args:
        text: The raw user input text

    Returns:
        ParsedCommand if input starts with /, None otherwise

    Examples:
        "/help" -> ParsedCommand(name="help", args="", raw="/help")
        "/mode plan" -> ParsedCommand(name="mode", args="plan", raw="/mode plan")
        "/skill my-skill" -> ParsedCommand(name="skill", args="my-skill", raw="/skill my-skill")
        "hello" -> None
    """
    text = text.strip()

    if not text.startswith("/"):
        return None

    # Match: /command [args]
    match = re.match(r"^/(\w+)(?:\s+(.*))?$", text, re.DOTALL)
    if not match:
        return None

    name = match.group(1).lower()
    args = (match.group(2) or "").strip()

    return ParsedCommand(name=name, args=args, raw=text)


def is_slash_command(text: str) -> bool:
    """Check if text is a slash command."""
    return parse_slash_command(text) is not None


# =============================================================================
# Command Handler
# =============================================================================


class SlashCommandHandler:
    """Executes slash commands against an Amplifier session.

    Each command method follows the pattern:
    - Takes ParsedCommand and session
    - Returns SlashCommandResult
    - May modify session state (e.g., mode activation)
    """

    def __init__(self, session: Any) -> None:
        self._session = session
        self._active_mode: str | None = None

    async def execute(self, command: ParsedCommand) -> SlashCommandResult:
        """Execute a slash command.

        Routes to the appropriate handler method based on command name.
        """
        handler_name = f"_handle_{command.name}"
        handler = getattr(self, handler_name, None)

        if handler is None:
            return SlashCommandResult(
                success=False,
                message=f"Unknown command: /{command.name}. Type /help for available commands.",
            )

        try:
            return await handler(command)
        except Exception as e:
            logger.exception(f"Error executing /{command.name}: {e}")
            return SlashCommandResult(
                success=False,
                message=f"Error executing /{command.name}: {e}",
            )

    # -------------------------------------------------------------------------
    # Tier 1: Essential Commands
    # -------------------------------------------------------------------------

    async def _handle_help(self, command: ParsedCommand) -> SlashCommandResult:
        """Show available slash commands."""
        commands = SlashCommandRegistry.get_commands_for_session(self._session)

        lines = ["**Available Slash Commands:**", ""]
        for cmd in commands:
            if cmd.input and cmd.input.root:
                lines.append(f"- `/{cmd.name} <{cmd.input.root.hint}>` - {cmd.description}")
            else:
                lines.append(f"- `/{cmd.name}` - {cmd.description}")

        return SlashCommandResult(
            success=True,
            message="\n".join(lines),
            data={"commands": [c.name for c in commands]},
        )

    async def _handle_tools(self, command: ParsedCommand) -> SlashCommandResult:
        """List available tools."""
        tools = []

        try:
            if hasattr(self._session, "list_tools"):
                raw_tools = self._session.list_tools()
                for t in raw_tools:
                    if isinstance(t, dict):
                        tools.append(
                            {"name": t.get("name", ""), "description": t.get("description", "")}
                        )
                    elif hasattr(t, "name"):
                        tools.append({"name": t.name, "description": getattr(t, "description", "")})
        except Exception as e:
            logger.warning(f"Error listing tools: {e}")

        if not tools:
            return SlashCommandResult(
                success=True,
                message="No tools available.",
                data={"tools": []},
            )

        lines = ["**Available Tools:**", ""]
        for tool in sorted(tools, key=lambda t: t["name"]):
            desc = tool["description"]
            # Truncate long descriptions
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"- `{tool['name']}` - {desc}")

        return SlashCommandResult(
            success=True,
            message="\n".join(lines),
            data={"tools": tools},
        )

    async def _handle_agents(self, command: ParsedCommand) -> SlashCommandResult:
        """List available agents."""
        agents = []

        try:
            # Get agents from session config
            if hasattr(self._session, "_coordinator"):
                coordinator = self._session._coordinator
                if hasattr(coordinator, "config"):
                    agent_config = coordinator.config.get("agents", {})
                    for name, cfg in agent_config.items():
                        desc = (
                            cfg.get("description", "No description")
                            if isinstance(cfg, dict)
                            else "No description"
                        )
                        agents.append({"name": name, "description": desc})
        except Exception as e:
            logger.warning(f"Error listing agents: {e}")

        if not agents:
            return SlashCommandResult(
                success=True,
                message="No agents available. Agents are defined in bundle configuration.",
                data={"agents": []},
            )

        lines = ["**Available Agents:**", ""]
        for agent in sorted(agents, key=lambda a: a["name"]):
            lines.append(f"- `{agent['name']}` - {agent['description']}")

        return SlashCommandResult(
            success=True,
            message="\n".join(lines),
            data={"agents": agents},
        )

    async def _handle_status(self, command: ParsedCommand) -> SlashCommandResult:
        """Show session status."""
        status = {
            "session_id": getattr(self._session, "session_id", "unknown"),
            "bundle": "unknown",
            "provider": "unknown",
            "active_mode": self._active_mode,
        }

        try:
            if hasattr(self._session, "_coordinator"):
                coordinator = self._session._coordinator
                if hasattr(coordinator, "config"):
                    status["bundle"] = coordinator.config.get("bundle", "unknown")
                    # Try to get provider info
                    providers = coordinator.config.get("providers", {})
                    if providers:
                        status["provider"] = ", ".join(providers.keys())
        except Exception as e:
            logger.warning(f"Error getting status: {e}")

        lines = [
            "**Session Status:**",
            "",
            f"- Session ID: `{status['session_id']}`",
            f"- Bundle: `{status['bundle']}`",
            f"- Provider: `{status['provider']}`",
            f"- Active Mode: `{status['active_mode'] or 'none'}`",
        ]

        return SlashCommandResult(
            success=True,
            message="\n".join(lines),
            data=status,
        )

    async def _handle_clear(self, command: ParsedCommand) -> SlashCommandResult:
        """Clear conversation context."""
        try:
            if hasattr(self._session, "clear_context"):
                await self._session.clear_context()
            elif hasattr(self._session, "_context") and hasattr(self._session._context, "clear"):
                self._session._context.clear()

            return SlashCommandResult(
                success=True,
                message="Conversation context cleared.",
                data={"cleared": True},
            )
        except Exception as e:
            return SlashCommandResult(
                success=False,
                message=f"Failed to clear context: {e}",
            )

    async def _handle_mode(self, command: ParsedCommand) -> SlashCommandResult:
        """Activate or deactivate a mode."""
        mode_name = command.args.strip().lower()

        if not mode_name:
            if self._active_mode:
                return SlashCommandResult(
                    success=True,
                    message=f"Current mode: `{self._active_mode}`. Use `/mode off` to deactivate.",
                    data={"active_mode": self._active_mode},
                )
            else:
                return SlashCommandResult(
                    success=True,
                    message="No mode active. Use `/mode <name>` to activate or `/modes` to list.",
                    data={"active_mode": None},
                )

        if mode_name == "off":
            old_mode = self._active_mode
            self._active_mode = None
            return SlashCommandResult(
                success=True,
                message=f"Mode deactivated{f' (was: {old_mode})' if old_mode else ''}.",
                data={"active_mode": None, "previous_mode": old_mode},
                update_commands=True,
            )

        # Activate mode
        # TODO: Validate mode exists and load its configuration
        self._active_mode = mode_name
        return SlashCommandResult(
            success=True,
            message=f"Mode `{mode_name}` activated. Use `/mode off` to deactivate.",
            data={"active_mode": mode_name},
            update_commands=True,
        )

    async def _handle_modes(self, command: ParsedCommand) -> SlashCommandResult:
        """List available modes."""
        # Built-in modes that are always available
        modes = [
            {"name": "plan", "description": "Read-only analysis and planning, no modifications"},
            {"name": "explore", "description": "Zero-footprint codebase exploration"},
            {
                "name": "careful",
                "description": "Full capability with confirmation for destructive actions",
            },
        ]

        # TODO: Discover custom modes from:
        # - .amplifier/modes/
        # - ~/.amplifier/modes/
        # - Bundle modes/ directory

        lines = ["**Available Modes:**", ""]
        for mode in modes:
            active = " (active)" if mode["name"] == self._active_mode else ""
            lines.append(f"- `{mode['name']}`{active} - {mode['description']}")

        lines.extend(
            [
                "",
                "Use `/mode <name>` to activate, `/mode off` to deactivate.",
            ]
        )

        return SlashCommandResult(
            success=True,
            message="\n".join(lines),
            data={"modes": modes, "active_mode": self._active_mode},
        )

    # -------------------------------------------------------------------------
    # Tier 2: Mode Shortcuts and Skills
    # -------------------------------------------------------------------------

    async def _handle_plan(self, command: ParsedCommand) -> SlashCommandResult:
        """Shortcut for /mode plan."""
        return await self._handle_mode(ParsedCommand(name="mode", args="plan", raw="/plan"))

    async def _handle_explore(self, command: ParsedCommand) -> SlashCommandResult:
        """Shortcut for /mode explore."""
        return await self._handle_mode(ParsedCommand(name="mode", args="explore", raw="/explore"))

    async def _handle_careful(self, command: ParsedCommand) -> SlashCommandResult:
        """Shortcut for /mode careful."""
        return await self._handle_mode(ParsedCommand(name="mode", args="careful", raw="/careful"))

    async def _handle_skills(self, command: ParsedCommand) -> SlashCommandResult:
        """List available skills."""
        # TODO: Implement skill discovery
        # Skills are in:
        # - .amplifier/skills/
        # - ~/.amplifier/skills/
        # - Configured git URLs

        return SlashCommandResult(
            success=True,
            message=(
                "Skill discovery not yet implemented. Use the `load_skill` tool with `list=true`."
            ),
            data={"skills": []},
        )

    async def _handle_skill(self, command: ParsedCommand) -> SlashCommandResult:
        """Load a skill by name."""
        skill_name = command.args.strip()

        if not skill_name:
            return SlashCommandResult(
                success=False,
                message="Please specify a skill name: `/skill <name>`",
            )

        # TODO: Implement skill loading
        return SlashCommandResult(
            success=True,
            message=(
                f"Skill loading not yet implemented. "
                f'Use the `load_skill` tool with `skill_name="{skill_name}"`.'
            ),
            data={"skill": skill_name},
        )

    async def _handle_config(self, command: ParsedCommand) -> SlashCommandResult:
        """Show current configuration."""
        config = {}

        try:
            if hasattr(self._session, "_coordinator"):
                coordinator = self._session._coordinator
                if hasattr(coordinator, "config"):
                    # Get safe subset of config
                    full_config = coordinator.config
                    config = {
                        "bundle": full_config.get("bundle"),
                        "providers": list(full_config.get("providers", {}).keys()),
                        "tools_count": len(full_config.get("tools", [])),
                        "agents_count": len(full_config.get("agents", {})),
                        "hooks_count": len(full_config.get("hooks", [])),
                    }
        except Exception as e:
            logger.warning(f"Error getting config: {e}")

        lines = [
            "**Current Configuration:**",
            "",
            f"- Bundle: `{config.get('bundle', 'unknown')}`",
            f"- Providers: `{', '.join(config.get('providers', [])) or 'none'}`",
            f"- Tools: {config.get('tools_count', 0)}",
            f"- Agents: {config.get('agents_count', 0)}",
            f"- Hooks: {config.get('hooks_count', 0)}",
        ]

        return SlashCommandResult(
            success=True,
            message="\n".join(lines),
            data=config,
        )

    # -------------------------------------------------------------------------
    # Tier 3: Recipe Commands
    # -------------------------------------------------------------------------

    async def _handle_recipe(self, command: ParsedCommand) -> SlashCommandResult:
        """Execute or manage recipes."""
        args = command.args.strip()

        if not args:
            return SlashCommandResult(
                success=True,
                message=(
                    "**Recipe Commands:**\n\n"
                    "- `/recipe run <path>` - Execute a recipe\n"
                    "- `/recipe list` - List active recipe sessions\n"
                    "- `/recipe resume <id>` - Resume interrupted recipe\n"
                    "- `/recipe approve <id> <stage>` - Approve pending stage\n"
                    "- `/recipe cancel <id>` - Cancel running recipe\n"
                ),
                data={},
            )

        parts = args.split(maxsplit=1)
        subcommand = parts[0].lower()
        subargs = parts[1] if len(parts) > 1 else ""

        # Route to subcommand handlers
        if subcommand == "list":
            return await self._recipe_list()
        elif subcommand == "run":
            return await self._recipe_run(subargs)
        elif subcommand == "resume":
            return await self._recipe_resume(subargs)
        elif subcommand == "approve":
            return await self._recipe_approve(subargs)
        elif subcommand == "cancel":
            return await self._recipe_cancel(subargs)
        else:
            return SlashCommandResult(
                success=False,
                message=f"Unknown recipe subcommand: `{subcommand}`. Use `/recipe` for help.",
            )

    async def _recipe_list(self) -> SlashCommandResult:
        """List active recipe sessions.

        Translates to Amplifier prompt for proper orchestration.
        """
        return SlashCommandResult(
            success=True,
            message="Listing active recipe sessions...",
            send_as_message=False,  # Don't send this, let Amplifier respond
            execute_as_prompt=(
                "Use the recipes tool to list active recipe sessions. "
                "Show the session IDs, recipe names, and current status."
            ),
        )

    async def _recipe_run(self, path: str) -> SlashCommandResult:
        """Execute a recipe.

        Translates to Amplifier prompt for proper orchestration.
        The recipes tool will be invoked with full context and capabilities.
        """
        if not path:
            return SlashCommandResult(
                success=False,
                message="Please specify a recipe path: `/recipe run <path>`",
            )

        # Parse optional context variables: /recipe run path.yaml key=value key2=value2
        parts = path.split()
        recipe_path = parts[0]
        context_vars = {}

        if len(parts) > 1:
            for part in parts[1:]:
                if "=" in part:
                    key, value = part.split("=", 1)
                    context_vars[key] = value

        # Build prompt for Amplifier
        prompt = f'Execute the recipe at "{recipe_path}" using the recipes tool.'
        if context_vars:
            context_str = ", ".join(f'{k}="{v}"' for k, v in context_vars.items())
            prompt += f" Pass these context variables: {context_str}."

        return SlashCommandResult(
            success=True,
            message=f"Starting recipe: {recipe_path}",
            send_as_message=False,
            execute_as_prompt=prompt,
            data={"recipe_path": recipe_path, "context": context_vars},
        )

    async def _recipe_resume(self, session_id: str) -> SlashCommandResult:
        """Resume an interrupted recipe.

        Translates to Amplifier prompt for proper orchestration.
        """
        if not session_id:
            return SlashCommandResult(
                success=False,
                message="Please specify a session ID: `/recipe resume <id>`",
            )

        return SlashCommandResult(
            success=True,
            message=f"Resuming recipe session: {session_id}",
            send_as_message=False,
            execute_as_prompt=(
                f'Resume the recipe session with ID "{session_id}" using the recipes tool.'
            ),
            data={"session_id": session_id},
        )

    async def _recipe_approve(self, args: str) -> SlashCommandResult:
        """Approve a pending recipe stage.

        Translates to Amplifier prompt for proper orchestration.
        """
        parts = args.split()
        if len(parts) < 2:
            return SlashCommandResult(
                success=False,
                message="Please specify session ID and stage: `/recipe approve <id> <stage>`",
            )

        session_id, stage = parts[0], parts[1]

        return SlashCommandResult(
            success=True,
            message=f"Approving stage '{stage}' for session {session_id}",
            send_as_message=False,
            execute_as_prompt=(
                f'Approve the stage "{stage}" for recipe session "{session_id}" '
                "using the recipes tool."
            ),
            data={"session_id": session_id, "stage": stage},
        )

    async def _recipe_cancel(self, session_id: str) -> SlashCommandResult:
        """Cancel a running recipe.

        Translates to Amplifier prompt for proper orchestration.
        """
        if not session_id:
            return SlashCommandResult(
                success=False,
                message="Please specify a session ID: `/recipe cancel <id>`",
            )

        return SlashCommandResult(
            success=True,
            message=f"Cancelling recipe session: {session_id}",
            send_as_message=False,
            execute_as_prompt=(
                f'Cancel the recipe session with ID "{session_id}" using the recipes tool.'
            ),
            data={"session_id": session_id},
        )


# =============================================================================
# ACP Integration Helpers
# =============================================================================


def create_available_commands_update(
    session: Any | None = None,
) -> AvailableCommandsUpdate:
    """Create an ACP AvailableCommandsUpdate notification.

    This should be sent after session creation to advertise available commands.
    """
    commands = SlashCommandRegistry.get_commands_for_session(session)

    return AvailableCommandsUpdate(
        session_update="available_commands_update",
        available_commands=commands,
    )
