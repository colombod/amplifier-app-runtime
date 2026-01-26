"""Amplifier Server CLI.

Commands:
    amplifier-server serve    - Run headless HTTP server
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
    """Run the Amplifier server."""
    import uvicorn

    click.echo(f"Starting Amplifier server on http://{host}:{port}")
    click.echo("Press Ctrl+C to stop")

    uvicorn.run(
        "amplifier_server_app.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


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
