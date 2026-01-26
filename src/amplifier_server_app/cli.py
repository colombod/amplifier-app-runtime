"""Amplifier Server CLI.

Commands:
    amplifier-server serve    - Run headless HTTP server
    amplifier-server stdio    - Run in stdio mode (for subprocess/IPC)
    amplifier-server health   - Check server health
"""

import asyncio
import sys

import click
import httpx


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx: click.Context) -> None:
    """Amplifier Server - HTTP API for AI agent sessions."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=4096, help="Port to bind to")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development")
def serve(host: str, port: int, reload: bool) -> None:
    """Run the Amplifier server (HTTP mode)."""
    import uvicorn

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

    Reads JSON objects from stdin (one per line).
    Writes JSON objects to stdout (one per line).

    Example usage from Python:

        proc = subprocess.Popen(
            ["amplifier-server", "stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

        # Send a message
        proc.stdin.write(json.dumps({"type": "prompt", "content": "Hello"}) + "\\n")
        proc.stdin.flush()

        # Read responses
        for line in proc.stdout:
            event = json.loads(line)
            print(event)

    Example usage from Node.js:

        const { spawn } = require('child_process');
        const server = spawn('amplifier-server', ['stdio']);

        server.stdin.write(JSON.stringify({type: 'prompt', content: 'Hello'}) + '\\n');

        server.stdout.on('data', (data) => {
            const event = JSON.parse(data.toString());
            console.log(event);
        });
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


if __name__ == "__main__":
    main()
