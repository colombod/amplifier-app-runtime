"""Canonical sources for provider modules.

Based on amplifier-app-cli's provider_sources.py - provides the same
provider installation capabilities for amplifier-app-runtime.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import site
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Single source of truth for known provider git URLs
DEFAULT_PROVIDER_SOURCES: dict[str, str] = {
    "provider-anthropic": "git+https://github.com/microsoft/amplifier-module-provider-anthropic@main",
    "provider-azure-openai": "git+https://github.com/microsoft/amplifier-module-provider-azure-openai@main",
    "provider-gemini": "git+https://github.com/microsoft/amplifier-module-provider-gemini@main",
    "provider-ollama": "git+https://github.com/microsoft/amplifier-module-provider-ollama@main",
    "provider-openai": "git+https://github.com/microsoft/amplifier-module-provider-openai@main",
    "provider-vllm": "git+https://github.com/microsoft/amplifier-module-provider-vllm@main",
}

# Runtime dependencies between providers.
# Some providers extend others (e.g., Azure OpenAI extends OpenAI's provider class).
# Format: {"dependent": ["dependency1", "dependency2", ...]}
PROVIDER_DEPENDENCIES: dict[str, list[str]] = {
    "provider-azure-openai": ["provider-openai"],  # AzureOpenAIProvider extends OpenAIProvider
}

# Mapping of provider names to their environment variable
PROVIDER_ENV_VARS: dict[str, str] = {
    "provider-anthropic": "ANTHROPIC_API_KEY",
    "provider-openai": "OPENAI_API_KEY",
    "provider-azure-openai": "AZURE_OPENAI_API_KEY",
    "provider-gemini": "GOOGLE_API_KEY",
    "provider-ollama": "OLLAMA_HOST",  # Ollama doesn't need API key, but host can be configured
    "provider-vllm": "VLLM_API_BASE",  # vLLM server URL
}


def _get_ordered_providers(sources: dict[str, str]) -> list[tuple[str, str]]:
    """Order providers so dependencies are installed first (topological sort).

    Ensures providers that depend on others are installed after their dependencies.
    For example, provider-azure-openai depends on provider-openai at runtime.

    Args:
        sources: Dict mapping module_id to source URI

    Returns:
        List of (module_id, source_uri) tuples in dependency-respecting order
    """
    ordered: list[tuple[str, str]] = []
    remaining = set(sources.keys())

    while remaining:
        # Find providers whose dependencies are all satisfied (not in remaining)
        ready = [
            p
            for p in remaining
            if all(dep not in remaining for dep in PROVIDER_DEPENDENCIES.get(p, []))
        ]

        if not ready:
            # No providers ready - either circular dependency or dependency not in sources.
            # Fall back to taking any remaining provider to avoid infinite loop.
            ready = [sorted(remaining)[0]]
            logger.debug(f"Dependency ordering: no ready providers, falling back to {ready[0]}")

        # Process ready providers in sorted order for determinism
        for provider in sorted(ready):
            ordered.append((provider, sources[provider]))
            remaining.remove(provider)

    return ordered


def is_local_path(source_uri: str) -> bool:
    """Check if source URI is a local file path.

    Args:
        source_uri: Source URI string

    Returns:
        True if local path (starts with /, ./, ../, or file://)
    """
    return (
        source_uri.startswith("/")
        or source_uri.startswith("./")
        or source_uri.startswith("../")
        or source_uri.startswith("file://")
    )


def _resolve_git_source(source_uri: str) -> Path:
    """Resolve a git source URI to a local path.

    Uses amplifier-foundation's SimpleSourceResolver for caching.

    Args:
        source_uri: Git URL (git+https://...)

    Returns:
        Path to cached module directory
    """
    import asyncio

    from amplifier_foundation.paths.resolution import get_amplifier_home
    from amplifier_foundation.sources import SimpleSourceResolver

    cache_dir = get_amplifier_home() / "cache"
    resolver = SimpleSourceResolver(cache_dir=cache_dir)

    # Run async resolver
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(resolver.resolve(source_uri))
        return result.active_path
    finally:
        loop.close()


def _resolve_source(source_uri: str) -> Path:
    """Resolve source URI to local path.

    Args:
        source_uri: Git URL or local path

    Returns:
        Path to module directory
    """
    if is_local_path(source_uri):
        # Local path - resolve directly
        if source_uri.startswith("file://"):
            source_uri = source_uri[7:]
        return Path(source_uri).resolve()
    else:
        # Git URL - use foundation resolver
        return _resolve_git_source(source_uri)


def install_known_providers(
    verbose: bool = True,
    quiet: bool = False,
) -> list[str]:
    """Install all known provider modules.

    Downloads and caches all known providers so they can be discovered
    and used at runtime.

    Args:
        verbose: Whether to show progress messages
        quiet: If True, suppress all output (overrides verbose)

    Returns:
        List of successfully installed provider module IDs
    """
    installed: list[str] = []
    failed: list[tuple[str, str]] = []

    # Order providers so dependencies are installed first
    ordered_providers = _get_ordered_providers(DEFAULT_PROVIDER_SOURCES)

    for module_id, source_uri in ordered_providers:
        try:
            if verbose and not quiet:
                print(f"  Installing {module_id}...", end="", flush=True)

            # Resolve source to local path
            module_path = _resolve_source(source_uri)

            # Install editable so cache updates are immediately effective
            result = subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "-e",
                    str(module_path),
                    "--python",
                    sys.executable,
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Failed to install: {result.stderr}")

            if verbose and not quiet:
                suffix = " (local)" if is_local_path(source_uri) else ""
                print(f" ✓{suffix}")

            installed.append(module_id)
            logger.info(f"Installed provider: {module_id}")

        except Exception as e:
            failed.append((module_id, str(e)))
            logger.warning(f"Failed to install {module_id}: {e}")

            if verbose and not quiet:
                print(f" ✗ ({e})")

    if failed and verbose and not quiet:
        print(f"\n⚠️  {len(failed)} provider(s) failed to install")

    # Refresh Python's view of installed packages
    if installed:
        importlib.invalidate_caches()

        # Re-add site directories to ensure newly installed packages are found
        for site_dir in site.getsitepackages():
            site.addsitedir(site_dir)

        # Force refresh of importlib.metadata distributions cache
        if hasattr(importlib.metadata, "distributions"):
            list(importlib.metadata.distributions())

    return installed


def get_installed_providers() -> list[dict[str, Any]]:
    """Get list of installed provider modules.

    Checks which known providers are actually installed and importable.

    Returns:
        List of dicts with module_id, display_name, and installed status
    """
    providers = []

    for module_id in DEFAULT_PROVIDER_SOURCES:
        provider_name = module_id.replace("provider-", "")
        module_name = f"amplifier_module_provider_{provider_name.replace('-', '_')}"

        try:
            importlib.import_module(module_name)
            installed = True
        except ImportError:
            installed = False

        # Get display name
        display_names = {
            "anthropic": "Anthropic",
            "openai": "OpenAI",
            "azure-openai": "Azure OpenAI",
            "gemini": "Google Gemini",
            "ollama": "Ollama",
            "vllm": "vLLM",
        }
        display_name = display_names.get(provider_name, provider_name.title())

        providers.append(
            {
                "module_id": module_id,
                "name": provider_name,
                "display_name": display_name,
                "installed": installed,
                "env_var": PROVIDER_ENV_VARS.get(module_id),
            }
        )

    return providers


__all__ = [
    "DEFAULT_PROVIDER_SOURCES",
    "PROVIDER_DEPENDENCIES",
    "PROVIDER_ENV_VARS",
    "get_installed_providers",
    "install_known_providers",
    "is_local_path",
]
