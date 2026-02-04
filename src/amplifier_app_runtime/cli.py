"""Amplifier Runtime CLI.

Default mode is stdio (for IDE/subprocess integration).
Use --http to run as HTTP server.

Usage:
    amplifier-runtime                     # Stdio mode (default)
    amplifier-runtime --http              # HTTP server mode
    amplifier-runtime --http --port 8080  # HTTP with custom port
    amplifier-runtime --http --acp        # HTTP with ACP endpoints
    amplifier-runtime --health            # Check HTTP server health

    amplifier-runtime session list        # List saved sessions
    amplifier-runtime session info <id>   # Show session details
    amplifier-runtime session resume <id> # Resume a session
    amplifier-runtime session delete <id> # Delete a session

    amplifier-runtime bundle list         # List available bundles
    amplifier-runtime bundle info <name>  # Show bundle details

    amplifier-runtime provider list       # List providers
    amplifier-runtime provider check <n>  # Check provider status

    amplifier-runtime config              # Show configuration
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from typing import TYPE_CHECKING

import click
import httpx

if TYPE_CHECKING:
    pass

# Output format options
FORMAT_TABLE = "table"
FORMAT_JSON = "json"


def format_datetime(dt: datetime | str | None) -> str:
    """Format datetime for display."""
    if dt is None:
        return "N/A"
    if isinstance(dt, str):
        # Parse ISO format
        try:
            dt = datetime.fromisoformat(dt.rstrip("Z"))
        except ValueError:
            return dt
    return dt.strftime("%Y-%m-%d %H:%M")


def truncate(text: str | None, max_len: int = 50) -> str:
    """Truncate text for display."""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


@click.group(invoke_without_command=True)
@click.option("--http", "http_mode", is_flag=True, help="Run as HTTP server instead of stdio")
@click.option("--host", default="127.0.0.1", help="Host to bind to (HTTP mode)")
@click.option("--port", default=4096, help="Port to bind to (HTTP mode)")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development (HTTP mode)")
@click.option("--acp", "acp_enabled", is_flag=True, help="Enable ACP endpoints (HTTP mode)")
@click.option("--health", "health_check", is_flag=True, help="Check HTTP server health and exit")
@click.option("--health-url", default="http://localhost:4096", help="Server URL for health check")
@click.option(
    "--host-tools",
    "host_tools_path",
    type=click.Path(exists=True),
    help="Path to YAML file defining host tools",
)
@click.option(
    "--host-tools-module",
    "host_tools_module",
    help="Python module containing host tool definitions (e.g., myapp.tools)",
)
@click.pass_context
def main(
    ctx: click.Context,
    http_mode: bool,
    host: str,
    port: int,
    reload: bool,
    acp_enabled: bool,
    health_check: bool,
    health_url: str,
    host_tools_path: str | None,
    host_tools_module: str | None,
) -> None:
    """Amplifier Runtime - AI agent server for IDE integrations.

    By default, runs in stdio mode for subprocess/IPC communication.
    Use --http to run as an HTTP server.
    """
    # If a subcommand is invoked, let it handle everything
    if ctx.invoked_subcommand is not None:
        return

    # Validate flag combinations
    if acp_enabled and not http_mode:
        raise click.UsageError(
            "--acp requires --http mode. "
            "ACP endpoints are only available when running as an HTTP server.\n\n"
            "Usage:\n"
            "  amplifier-runtime --http --acp     # HTTP server with ACP endpoints\n"
            "  amplifier-runtime                  # Stdio mode (no ACP endpoints)"
        )

    if reload and not http_mode:
        raise click.UsageError(
            "--reload requires --http mode. "
            "Auto-reload is only available when running as an HTTP server."
        )

    if (host != "127.0.0.1" or port != 4096) and not http_mode and not health_check:
        raise click.UsageError(
            "--host and --port require --http mode. "
            "These options are only available when running as an HTTP server."
        )

    # Handle --health flag
    if health_check:
        _do_health_check(health_url)
        return

    # Load host tools if specified
    if host_tools_path or host_tools_module:
        _load_host_tools(host_tools_path, host_tools_module)

    # Run in appropriate mode
    if http_mode:
        _run_http_server(host, port, reload, acp_enabled)
    else:
        _run_stdio_server()


def _load_host_tools(yaml_path: str | None, module_name: str | None) -> None:
    """Load host tools from YAML file or Python module.

    Args:
        yaml_path: Path to YAML file defining tools
        module_name: Python module containing tool definitions
    """
    from .host_tools import HostToolDefinition, host_tool_registry

    tools_loaded = 0

    # Load from YAML file
    if yaml_path:
        import importlib

        import yaml

        click.echo(f"Loading host tools from {yaml_path}", err=True)

        with open(yaml_path) as f:
            config = yaml.safe_load(f)

        tools_config = config.get("tools", [])
        for tool_config in tools_config:
            name = tool_config.get("name")
            description = tool_config.get("description", "")
            parameters = tool_config.get("parameters", {"type": "object"})
            module_path = tool_config.get("module")
            function_name = tool_config.get("function")

            if not all([name, module_path, function_name]):
                click.echo(
                    f"Skipping incomplete tool definition: {tool_config}",
                    err=True,
                )
                continue

            try:
                # Import the handler function
                mod = importlib.import_module(module_path)
                handler = getattr(mod, function_name)

                # Register the tool
                definition = HostToolDefinition(
                    name=name,
                    description=description,
                    parameters=parameters,
                    handler=handler,
                    requires_approval=tool_config.get("requires_approval", False),
                    timeout=tool_config.get("timeout"),
                    category=tool_config.get("category"),
                )
                asyncio.run(host_tool_registry.register(definition))
                tools_loaded += 1
                click.echo(f"  Registered: {name}", err=True)

            except Exception as e:
                click.echo(f"  Failed to load {name}: {e}", err=True)

    # Load from Python module
    if module_name:
        import importlib

        click.echo(f"Loading host tools from module {module_name}", err=True)

        try:
            # Import the module - this will trigger any @host_tool decorators
            mod = importlib.import_module(module_name)

            # Look for a setup function
            if hasattr(mod, "setup_host_tools"):
                setup_fn = mod.setup_host_tools
                if asyncio.iscoroutinefunction(setup_fn):
                    asyncio.run(setup_fn(host_tool_registry))
                else:
                    setup_fn(host_tool_registry)

            # Count tools registered
            tools_loaded = host_tool_registry.count
            click.echo(f"  Module loaded, {tools_loaded} tools registered", err=True)

        except ImportError as e:
            click.echo(f"Failed to import module {module_name}: {e}", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"Error loading tools from {module_name}: {e}", err=True)
            sys.exit(1)

    if tools_loaded > 0:
        click.echo(f"Total host tools loaded: {tools_loaded}", err=True)


def _do_health_check(url: str) -> None:
    """Check server health."""

    async def check() -> None:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{url}/health")
                if response.status_code == 200:
                    data = response.json()
                    click.echo(f"Server is healthy: {data}")
                else:
                    click.echo(f"Server returned {response.status_code}", err=True)
                    sys.exit(1)
        except httpx.ConnectError:
            click.echo(f"Cannot connect to server at {url}", err=True)
            sys.exit(1)

    asyncio.run(check())


def _run_http_server(host: str, port: int, reload: bool, acp_enabled: bool) -> None:
    """Run HTTP server mode."""
    import os

    import uvicorn

    # Pass ACP flag via environment variable for the app factory
    if acp_enabled:
        os.environ["AMPLIFIER_ACP_ENABLED"] = "1"
        click.echo(f"Starting Amplifier runtime on http://{host}:{port} (ACP enabled)", err=True)
        click.echo("  ACP endpoints: /acp/rpc, /acp/events, /acp/ws", err=True)
    else:
        os.environ.pop("AMPLIFIER_ACP_ENABLED", None)
        click.echo(f"Starting Amplifier runtime on http://{host}:{port}", err=True)

    click.echo("Press Ctrl+C to stop", err=True)

    uvicorn.run(
        "amplifier_app_runtime.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


def _run_stdio_server() -> None:
    """Run stdio server mode (default)."""
    from .acp import run_stdio_agent

    click.echo("Starting Amplifier runtime in stdio mode", err=True)

    try:
        asyncio.run(run_stdio_agent())
    except KeyboardInterrupt:
        click.echo("\nShutting down", err=True)


# =============================================================================
# Session Commands
# =============================================================================


@main.group()
def session() -> None:
    """Manage saved sessions."""


@session.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include sub-sessions (spawned agents)")
@click.option("--limit", "-n", default=20, help="Maximum sessions to show")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice([FORMAT_TABLE, FORMAT_JSON]),
    default=FORMAT_TABLE,
    help="Output format",
)
def session_list(show_all: bool, limit: int, output_format: str) -> None:
    """List saved sessions.

    Examples:

        # List recent sessions
        amplifier-runtime session list

        # Include agent sub-sessions
        amplifier-runtime session list --all

        # JSON output for scripting
        amplifier-runtime session list --format json
    """
    from .session_store import SessionStore

    store = SessionStore()
    sessions = store.list_sessions(
        top_level_only=not show_all,
        min_turns=0 if show_all else 1,
        limit=limit,
    )

    if not sessions:
        click.echo("No sessions found.")
        return

    if output_format == FORMAT_JSON:
        click.echo(json.dumps(sessions, indent=2, ensure_ascii=False, default=str))
        return

    # Table format
    click.echo(f"{'ID':<20} {'Bundle':<15} {'Turns':>6} {'Updated':<17} {'State':<10}")
    click.echo("-" * 75)

    for s in sessions:
        session_id = s.get("session_id", "?")[:20]
        bundle = truncate(s.get("bundle_name") or "default", 15)
        turns = s.get("turn_count", 0)
        updated = format_datetime(s.get("updated_at"))
        state = s.get("state", "?")[:10]

        click.echo(f"{session_id:<20} {bundle:<15} {turns:>6} {updated:<17} {state:<10}")

    click.echo(f"\nTotal: {len(sessions)} session(s)")


@session.command("info")
@click.argument("session_id")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice([FORMAT_TABLE, FORMAT_JSON]),
    default=FORMAT_TABLE,
    help="Output format",
)
@click.option("--transcript", "-t", is_flag=True, help="Include conversation transcript")
def session_info(session_id: str, output_format: str, transcript: bool) -> None:
    """Show detailed information about a session.

    Examples:

        # Show session info
        amplifier-runtime session info sess_abc123

        # Include transcript
        amplifier-runtime session info sess_abc123 --transcript

        # JSON output
        amplifier-runtime session info sess_abc123 --format json --transcript
    """
    from .session_store import SessionStore

    store = SessionStore()
    info = store.get_session_summary(session_id)

    if info is None:
        click.echo(f"Session not found: {session_id}", err=True)
        sys.exit(1)

    if transcript:
        info["transcript"] = store.load_transcript(session_id)

    if output_format == FORMAT_JSON:
        click.echo(json.dumps(info, indent=2, ensure_ascii=False, default=str))
        return

    # Table format
    click.echo(f"Session: {info.get('session_id')}")
    click.echo(f"Bundle:  {info.get('bundle_name') or 'default'}")
    click.echo(f"State:   {info.get('state', 'unknown')}")
    click.echo(f"Turns:   {info.get('turn_count', 0)}")
    click.echo(f"Created: {format_datetime(info.get('created_at'))}")
    click.echo(f"Updated: {format_datetime(info.get('updated_at'))}")

    if info.get("cwd"):
        click.echo(f"CWD:     {info.get('cwd')}")

    if info.get("parent_session_id"):
        click.echo(f"Parent:  {info.get('parent_session_id')}")

    if info.get("error"):
        click.echo(f"Error:   {info.get('error')}")

    # Preview
    if info.get("first_user_message"):
        click.echo(f"\nFirst prompt: {info.get('first_user_message')}")

    if info.get("last_assistant_message"):
        click.echo(f"Last response: {info.get('last_assistant_message')}")

    # Transcript
    if transcript and info.get("transcript"):
        click.echo("\n--- Transcript ---")
        for msg in info["transcript"]:
            role = msg.get("role", "?").upper()
            content = msg.get("content", "")
            if isinstance(content, str):
                content = truncate(content, 200)
            click.echo(f"\n[{role}]")
            click.echo(content)


@session.command("resume")
@click.argument("session_id")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def session_resume(session_id: str, output_json: bool) -> None:
    """Resume a session and show its state.

    Examples:

        # Show session state
        amplifier-runtime session resume sess_abc123

        # JSON output
        amplifier-runtime session resume sess_abc123 --json
    """
    from .session import SessionManager

    async def execute() -> None:
        manager = SessionManager()
        managed_session = await manager.resume(session_id)

        if not managed_session:
            click.echo(f"Session not found: {session_id}", err=True)
            sys.exit(1)

        click.echo(f"Resumed session {session_id}", err=True)
        click.echo(
            f"Turn count: {managed_session.metadata.turn_count}, "
            f"Messages: {len(managed_session.get_transcript())}",
            err=True,
        )

        if output_json:
            click.echo(json.dumps(managed_session.to_dict(), indent=2, default=str))

    asyncio.run(execute())


@session.command("delete")
@click.argument("session_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def session_delete(session_id: str, yes: bool) -> None:
    """Delete a saved session.

    Examples:

        # Delete with confirmation
        amplifier-runtime session delete sess_abc123

        # Skip confirmation
        amplifier-runtime session delete sess_abc123 --yes
    """
    from .session_store import SessionStore

    store = SessionStore()

    if not store.session_exists(session_id):
        click.echo(f"Session not found: {session_id}", err=True)
        sys.exit(1)

    if not yes and not click.confirm(f"Delete session {session_id}?"):
        click.echo("Cancelled.")
        return

    if store.delete_session(session_id):
        click.echo(f"Deleted session {session_id}")
    else:
        click.echo(f"Failed to delete session {session_id}", err=True)
        sys.exit(1)


@session.command("clear")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation", required=True)
def session_clear(yes: bool) -> None:
    """Delete all saved sessions.

    Examples:

        amplifier-runtime session clear --yes
    """
    from .session_store import SessionStore

    store = SessionStore()

    if not yes:
        click.echo("Must pass --yes to confirm deletion of all sessions.", err=True)
        sys.exit(1)

    count = store.delete_all_sessions(confirm=True)
    click.echo(f"Deleted {count} session(s)")


# =============================================================================
# Bundle Commands
# =============================================================================


@main.group()
def bundle() -> None:
    """Manage bundles."""


@bundle.command("list")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice([FORMAT_TABLE, FORMAT_JSON]),
    default=FORMAT_TABLE,
    help="Output format",
)
def bundle_list(output_format: str) -> None:
    """List available bundles.

    Examples:

        amplifier-runtime bundle list
        amplifier-runtime bundle list --format json
    """

    async def run() -> None:
        from .bundle_manager import BundleManager

        manager = BundleManager()
        bundles = await manager.list_bundles()

        if output_format == FORMAT_JSON:
            click.echo(
                json.dumps(
                    [{"name": b.name, "description": b.description, "uri": b.uri} for b in bundles],
                    indent=2,
                )
            )
            return

        click.echo(f"{'Name':<20} {'Description':<50}")
        click.echo("-" * 72)
        for b in bundles:
            click.echo(f"{b.name:<20} {truncate(b.description, 50):<50}")

    asyncio.run(run())


@bundle.command("info")
@click.argument("bundle_name")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice([FORMAT_TABLE, FORMAT_JSON]),
    default=FORMAT_TABLE,
    help="Output format",
)
def bundle_info(bundle_name: str, output_format: str) -> None:
    """Show information about a bundle.

    Examples:

        amplifier-runtime bundle info foundation
        amplifier-runtime bundle info amplifier-dev --format json
    """

    async def run() -> None:
        from .bundle_manager import BundleManager

        manager = BundleManager()
        try:
            prepared = await manager.load_and_prepare(bundle_name)

            info = {
                "name": bundle_name,
                "tools": [],
                "agents": [],
                "providers": [],
            }

            # Extract available tools
            if hasattr(prepared, "bundle") and hasattr(prepared.bundle, "tools"):
                info["tools"] = [
                    t.get("name", t.get("module", "unknown")) for t in (prepared.bundle.tools or [])
                ]

            # Extract available agents
            if hasattr(prepared, "bundle") and hasattr(prepared.bundle, "agents"):
                info["agents"] = list((prepared.bundle.agents or {}).keys())

            if output_format == FORMAT_JSON:
                click.echo(json.dumps(info, indent=2))
                return

            click.echo(f"Bundle: {bundle_name}")
            click.echo(f"Tools:  {', '.join(info['tools']) or 'none'}")
            click.echo(f"Agents: {', '.join(info['agents']) or 'none'}")

        except Exception as e:
            click.echo(f"Error loading bundle '{bundle_name}': {e}", err=True)
            sys.exit(1)

    asyncio.run(run())


# =============================================================================
# Provider Commands
# =============================================================================


@main.group()
def provider() -> None:
    """Manage providers."""


@provider.command("list")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice([FORMAT_TABLE, FORMAT_JSON]),
    default=FORMAT_TABLE,
    help="Output format",
)
def provider_list(output_format: str) -> None:
    """List available providers.

    Shows providers detected from environment variables.

    Examples:

        amplifier-runtime provider list
    """
    import os

    providers = []

    # Check for common provider API keys
    # Note: Default models are handled by the provider modules themselves
    provider_checks = [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("azure-openai", "AZURE_OPENAI_API_KEY"),
        ("google", "GOOGLE_API_KEY"),
    ]

    for name, env_var in provider_checks:
        providers.append(
            {
                "name": name,
                "env_var": env_var,
                "status": "configured" if os.getenv(env_var) else "not configured",
            }
        )

    if output_format == FORMAT_JSON:
        click.echo(json.dumps(providers, indent=2))
        return

    click.echo(f"{'Provider':<15} {'Status':<15} {'Env Var':<25}")
    click.echo("-" * 55)
    for p in providers:
        status_color = "green" if p["status"] == "configured" else "red"
        status_display = click.style(p["status"], fg=status_color)
        click.echo(f"{p['name']:<15} {status_display:<24} {p['env_var']:<25}")


@provider.command("check")
@click.argument("provider_name")
def provider_check(provider_name: str) -> None:
    """Check if a provider is configured and working.

    Examples:

        amplifier-runtime provider check anthropic
        amplifier-runtime provider check openai
    """
    import os

    env_vars = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "azure-openai": "AZURE_OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
    }

    env_var = env_vars.get(provider_name.lower())
    if not env_var:
        click.echo(f"Unknown provider: {provider_name}", err=True)
        click.echo(f"Available providers: {', '.join(env_vars.keys())}")
        sys.exit(1)

    if os.getenv(env_var):
        click.echo(f"{provider_name}: " + click.style("configured", fg="green"))
        click.echo(f"Environment variable {env_var} is set")
    else:
        click.echo(f"{provider_name}: " + click.style("not configured", fg="red"))
        click.echo(f"Set environment variable {env_var} to enable this provider")
        sys.exit(1)


# =============================================================================
# Config Command
# =============================================================================


@main.command("config")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def show_config(output_json: bool) -> None:
    """Show current configuration.

    Examples:

        amplifier-runtime config
        amplifier-runtime config --json
    """
    import os
    from pathlib import Path

    config = {
        "data_dir": str(Path.home() / ".amplifier-runtime"),
        "default_bundle": os.getenv("AMPLIFIER_BUNDLE", "foundation"),
        "default_provider": None,
        "providers_configured": [],
    }

    # Check configured providers
    provider_vars = [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("azure-openai", "AZURE_OPENAI_API_KEY"),
        ("google", "GOOGLE_API_KEY"),
    ]

    for name, env_var in provider_vars:
        if os.getenv(env_var):
            config["providers_configured"].append(name)
            if config["default_provider"] is None:
                config["default_provider"] = name

    if output_json:
        click.echo(json.dumps(config, indent=2))
        return

    click.echo("Amplifier Runtime Configuration")
    click.echo("-" * 40)
    click.echo(f"Data directory:     {config['data_dir']}")
    click.echo(f"Default bundle:     {config['default_bundle']}")
    click.echo(f"Default provider:   {config['default_provider'] or 'none'}")
    click.echo(f"Providers ready:    {', '.join(config['providers_configured']) or 'none'}")


if __name__ == "__main__":
    main()
