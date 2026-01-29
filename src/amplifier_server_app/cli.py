"""Amplifier Server CLI.

Commands:
    amplifier-server serve              - Run headless HTTP server
    amplifier-server stdio              - Run in stdio mode (for subprocess/IPC)
    amplifier-server health             - Check server health
    amplifier-server run "prompt"       - One-shot execution
    amplifier-server session list       - List saved sessions
    amplifier-server session info <id>  - Show session details
    amplifier-server session resume <id> - Resume and continue a session
    amplifier-server session delete <id> - Delete a session
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
    from .session import ManagedSession

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
@click.pass_context
def main(ctx: click.Context) -> None:
    """Amplifier Server - HTTP API for AI agent sessions."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# =============================================================================
# Server Commands
# =============================================================================


@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=4096, help="Port to bind to")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
@click.option("--acp-enabled", is_flag=True, help="Enable Agent Client Protocol (ACP) endpoints")
def serve(host: str, port: int, reload: bool, acp_enabled: bool) -> None:
    """Run the Amplifier server (HTTP mode).

    By default, only the core HTTP API is enabled. Use --acp-enabled to also
    expose ACP protocol endpoints for editor integrations (Zed, JetBrains, etc).
    """
    import os

    import uvicorn

    # Pass ACP flag via environment variable for the app factory
    if acp_enabled:
        os.environ["AMPLIFIER_ACP_ENABLED"] = "1"
        click.echo(f"Starting Amplifier server on http://{host}:{port} (ACP enabled)", err=True)
        click.echo("  ACP endpoints: /acp/rpc, /acp/events, /acp/ws", err=True)
    else:
        os.environ.pop("AMPLIFIER_ACP_ENABLED", None)
        click.echo(f"Starting Amplifier server on http://{host}:{port}", err=True)

    click.echo("Press Ctrl+C to stop", err=True)

    uvicorn.run(
        "amplifier_server_app.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


@main.command()
def stdio() -> None:
    """Run in stdio mode for subprocess/IPC communication.

    Reads JSON commands from stdin (one per line).
    Writes JSON events to stdout (one per line).
    """
    from .transport.stdio import Event, StdioTransport

    click.echo("Starting Amplifier server in stdio mode", err=True)
    click.echo("Reading from stdin, writing to stdout", err=True)

    async def handle_event(event: Event) -> Event | None:
        """Handle incoming events and return responses."""
        if event.type == "ping":
            return Event(type="pong", properties={})

        if event.type == "health":
            return Event(
                type="health_response",
                properties={"status": "ok", "mode": "stdio"},
            )

        if event.type == "prompt":
            # TODO: Integrate with actual session execution
            return Event(
                type="response",
                properties={
                    "message": "stdio mode active - session integration pending",
                    "received": event.properties,
                },
            )

        # Echo unknown events back with error
        return Event(
            type="error",
            properties={
                "error": "unknown_event_type",
                "received_type": event.type,
            },
        )

    async def run() -> None:
        transport = StdioTransport()
        await transport.run_loop(handle_event)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        click.echo("\nShutting down", err=True)


@main.command()
@click.option("--url", default="http://localhost:4096", help="Server URL")
def health(url: str) -> None:
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


# =============================================================================
# Run Command (One-shot execution)
# =============================================================================


@main.command("run")
@click.argument("prompt")
@click.option("--bundle", "-b", default=None, help="Bundle to use")
@click.option("--session", "-s", default=None, help="Session ID to continue")
@click.option("--max-turns", default=1, help="Maximum turns (default: 1 for one-shot)")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
@click.option("--quiet", "-q", is_flag=True, help="Only output the response")
def run_prompt(
    prompt: str,
    bundle: str | None,
    session: str | None,
    max_turns: int,
    output_json: bool,
    quiet: bool,
) -> None:
    """Execute a prompt and exit.

    Examples:

        # Simple one-shot
        amplifier-server run "What is 2+2?"

        # With specific bundle
        amplifier-server run "Analyze this code" --bundle foundation

        # Continue existing session
        amplifier-server run "And what about 3+3?" --session sess_abc123

        # JSON output for scripting
        amplifier-server run "List files" --json
    """
    from .session import SessionConfig, SessionManager

    async def execute() -> None:
        manager = SessionManager()

        # Resume existing or create new session
        managed_session: ManagedSession | None = None
        if session:
            managed_session = await manager.resume(session)
            if not managed_session:
                click.echo(f"Session not found: {session}", err=True)
                sys.exit(1)
            if not quiet:
                click.echo(f"Resuming session {session}", err=True)
        else:
            config = SessionConfig(bundle=bundle, max_turns=max_turns)
            managed_session = await manager.create(config=config)
            await managed_session.initialize()
            if not quiet:
                click.echo(f"Created session {managed_session.session_id}", err=True)

        # Collect response
        response_text = ""
        events_collected: list[dict] = []

        try:
            async for event in managed_session.execute(prompt):
                if output_json:
                    events_collected.append({"type": event.type, "properties": event.properties})

                # Collect text from content blocks
                if event.type == "content_block:delta":
                    delta = event.properties.get("delta", {})
                    if "text" in delta:
                        text = delta["text"]
                        response_text += text
                        if not quiet and not output_json:
                            click.echo(text, nl=False)

            if not quiet and not output_json:
                click.echo()  # Final newline

            if output_json:
                result = {
                    "session_id": managed_session.session_id,
                    "turn": managed_session.metadata.turn_count,
                    "response": response_text,
                    "events": events_collected,
                }
                click.echo(json.dumps(result, indent=2, ensure_ascii=False))

        except Exception as e:
            if output_json:
                click.echo(
                    json.dumps({"error": str(e), "type": type(e).__name__}),
                    err=True,
                )
            else:
                click.echo(f"Error: {e}", err=True)
            sys.exit(1)

    asyncio.run(execute())


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
        amplifier-server session list

        # Include agent sub-sessions
        amplifier-server session list --all

        # JSON output for scripting
        amplifier-server session list --format json
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
        amplifier-server session info sess_abc123

        # Include transcript
        amplifier-server session info sess_abc123 --transcript

        # JSON output
        amplifier-server session info sess_abc123 --format json --transcript
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
@click.argument("prompt", required=False)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def session_resume(session_id: str, prompt: str | None, output_json: bool) -> None:
    """Resume a session and optionally send a prompt.

    Examples:

        # Show session state (no prompt)
        amplifier-server session resume sess_abc123

        # Continue conversation
        amplifier-server session resume sess_abc123 "What else can you tell me?"
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

        if not prompt:
            # Just show info, don't execute
            if output_json:
                click.echo(json.dumps(managed_session.to_dict(), indent=2, default=str))
            return

        # Execute prompt
        response_text = ""
        events_collected: list[dict] = []

        async for event in managed_session.execute(prompt):
            if output_json:
                events_collected.append({"type": event.type, "properties": event.properties})

            if event.type == "content_block:delta":
                delta = event.properties.get("delta", {})
                if "text" in delta:
                    text = delta["text"]
                    response_text += text
                    if not output_json:
                        click.echo(text, nl=False)

        if not output_json:
            click.echo()

        if output_json:
            result = {
                "session_id": managed_session.session_id,
                "turn": managed_session.metadata.turn_count,
                "response": response_text,
                "events": events_collected,
            }
            click.echo(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(execute())


@session.command("delete")
@click.argument("session_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def session_delete(session_id: str, yes: bool) -> None:
    """Delete a saved session.

    Examples:

        # Delete with confirmation
        amplifier-server session delete sess_abc123

        # Skip confirmation
        amplifier-server session delete sess_abc123 --yes
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

        amplifier-server session clear --yes
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

        amplifier-server bundle list
        amplifier-server bundle list --format json
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

        amplifier-server bundle info foundation
        amplifier-server bundle info amplifier-dev --format json
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

        amplifier-server provider list
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

        amplifier-server provider check anthropic
        amplifier-server provider check openai
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
# Config Commands
# =============================================================================


@main.command("config")
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def show_config(output_json: bool) -> None:
    """Show current configuration.

    Examples:

        amplifier-server config
        amplifier-server config --json
    """
    import os
    from pathlib import Path

    config = {
        "data_dir": str(Path.home() / ".amplifier-server"),
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

    click.echo("Amplifier Server Configuration")
    click.echo("-" * 40)
    click.echo(f"Data directory:     {config['data_dir']}")
    click.echo(f"Default bundle:     {config['default_bundle']}")
    click.echo(f"Default provider:   {config['default_provider'] or 'none'}")
    click.echo(f"Providers ready:    {', '.join(config['providers_configured']) or 'none'}")


if __name__ == "__main__":
    main()
