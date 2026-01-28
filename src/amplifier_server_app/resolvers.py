"""App-layer module resolver with fallback policy.

Provides fallback resolution when modules aren't in the bundle,
following the same pattern as amplifier-app-cli's AppModuleResolver.

Per KERNEL_PHILOSOPHY.md: "Mechanism, not policy" - Foundation provides
capabilities, apps make decisions about how to use them.
"""

from __future__ import annotations

import asyncio
import logging
import os
from importlib import metadata
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ModuleResolutionError(Exception):
    """Error during module resolution."""

    pass


# =============================================================================
# Source Classes (simplified from CLI)
# =============================================================================


class GitSource:
    """Git source that uses foundation's SimpleSourceResolver."""

    def __init__(self, uri: str) -> None:
        """Initialize with git URI.

        Args:
            uri: Full git URI (e.g., git+https://github.com/org/repo@ref)
        """
        self.uri = uri
        self._resolver = None

    def _get_resolver(self) -> Any:
        """Lazily create the resolver."""
        if self._resolver is None:
            from amplifier_foundation.paths.resolution import get_amplifier_home
            from amplifier_foundation.sources import SimpleSourceResolver

            cache_dir = get_amplifier_home() / "cache"
            self._resolver = SimpleSourceResolver(cache_dir=cache_dir)
        return self._resolver

    def resolve(self) -> Path:
        """Resolve to cached git repository path (sync wrapper).

        Returns:
            Path to cached module directory.

        Raises:
            ModuleResolutionError: Clone/resolution failed.
        """
        from concurrent.futures import ThreadPoolExecutor

        from amplifier_foundation.exceptions import BundleNotFoundError

        resolver = self._get_resolver()

        def _run_async() -> Any:
            """Run the async resolver in a new event loop."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(resolver.resolve(self.uri))
            finally:
                loop.close()

        try:
            # Check if we're in an async context
            try:
                asyncio.get_running_loop()
                # We're in async context - run in thread pool
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_run_async)
                    result = future.result()
            except RuntimeError:
                # No running loop - we can safely create one directly
                result = _run_async()

            return result.active_path
        except BundleNotFoundError as e:
            raise ModuleResolutionError(str(e)) from e

    def __repr__(self) -> str:
        return f"GitSource({self.uri})"


class FileSource:
    """Local filesystem path source."""

    def __init__(self, path: str | Path) -> None:
        """Initialize with file path."""
        if isinstance(path, str):
            if path.startswith("file://"):
                path = path[7:]
            path = Path(path)
        self.path = path.resolve()

    def resolve(self) -> Path:
        """Resolve to filesystem path."""
        if not self.path.exists():
            raise ModuleResolutionError(f"Module path not found: {self.path}")
        if not self.path.is_dir():
            raise ModuleResolutionError(f"Module path is not a directory: {self.path}")
        return self.path

    def __repr__(self) -> str:
        return f"FileSource({self.path})"


class PackageSource:
    """Installed Python package source."""

    def __init__(self, package_name: str) -> None:
        """Initialize with package name."""
        self.package_name = package_name

    def resolve(self) -> Path:
        """Resolve to installed package path."""
        try:
            dist = metadata.distribution(self.package_name)
            if dist.files:
                package_files = [
                    f
                    for f in dist.files
                    if not any(part.endswith((".dist-info", ".data")) for part in f.parts)
                ]
                if package_files:
                    return Path(str(dist.locate_file(package_files[0]))).parent
                return Path(str(dist.locate_file(dist.files[0]))).parent
            return Path(str(dist.locate_file("")))
        except metadata.PackageNotFoundError as e:
            raise ModuleResolutionError(
                f"Package '{self.package_name}' not installed. "
                f"Install with: uv pip install {self.package_name}"
            ) from e

    def __repr__(self) -> str:
        return f"PackageSource({self.package_name})"


# =============================================================================
# Fallback Resolver
# =============================================================================


class FallbackResolver:
    """Fallback resolver using environment variables and installed packages.

    Resolution order (first match wins):
    1. Environment variable (AMPLIFIER_MODULE_<ID>)
    2. Installed package
    """

    def resolve(
        self, module_id: str, source_hint: str | None = None
    ) -> GitSource | FileSource | PackageSource:
        """Resolve module through fallback chain.

        Args:
            module_id: Module identifier (e.g., "provider-anthropic").
            source_hint: Optional source URI hint.

        Returns:
            Source object.

        Raises:
            ModuleResolutionError: Module not found.
        """
        # Layer 1: Environment variable
        env_key = f"AMPLIFIER_MODULE_{module_id.upper().replace('-', '_')}"
        if env_value := os.getenv(env_key):
            logger.debug(f"[module:resolve] {module_id} -> env var ({env_value})")
            return self._parse_source(env_value)

        # Layer 2: Source hint (from bundle config)
        if source_hint:
            logger.debug(f"[module:resolve] {module_id} -> source_hint")
            return self._parse_source(source_hint)

        # Layer 3: Installed package (fallback)
        logger.debug(f"[module:resolve] {module_id} -> package")
        return self._resolve_package(module_id)

    def _parse_source(self, source: str) -> GitSource | FileSource | PackageSource:
        """Parse source URI into Source instance."""
        if source.startswith("git+"):
            return GitSource(source)
        if source.startswith("file://") or source.startswith("/") or source.startswith("."):
            return FileSource(source)
        # Assume package name
        return PackageSource(source)

    def _resolve_package(self, module_id: str) -> PackageSource:
        """Resolve to installed package using fallback logic."""
        # Try exact ID
        try:
            metadata.distribution(module_id)
            return PackageSource(module_id)
        except metadata.PackageNotFoundError:
            pass

        # Try convention
        convention_name = f"amplifier-module-{module_id}"
        try:
            metadata.distribution(convention_name)
            return PackageSource(convention_name)
        except metadata.PackageNotFoundError:
            pass

        # Both failed
        raise ModuleResolutionError(
            f"Module '{module_id}' not found\n\n"
            f"Resolution attempted:\n"
            f"  1. Environment: AMPLIFIER_MODULE_{module_id.upper().replace('-', '_')} (not set)\n"
            f"  2. Package: Tried '{module_id}' and '{convention_name}' (neither installed)\n\n"
            f"Suggestions:\n"
            f"  - Add source to bundle: source: git+https://...\n"
            f"  - Install package: uv pip install <package-name>"
        )


# =============================================================================
# App Module Resolver (wraps bundle resolver with fallback)
# =============================================================================


class AppModuleResolver:
    """Composes bundle resolver with fallback policy.

    This is app-layer POLICY: when a module isn't in the bundle,
    try to resolve it from environment or installed packages.

    Use Case: A bundle might not include a provider, allowing users
    to use their preferred provider. The app-layer resolves the
    provider from environment or installed packages.
    """

    def __init__(
        self,
        bundle_resolver: Any,
        fallback_resolver: FallbackResolver | None = None,
    ) -> None:
        """Initialize with resolvers.

        Args:
            bundle_resolver: Foundation's BundleModuleResolver.
            fallback_resolver: Optional resolver for fallback.
        """
        self._bundle = bundle_resolver
        self._fallback = fallback_resolver or FallbackResolver()

    def resolve(self, module_id: str, source_hint: Any = None, profile_hint: Any = None) -> Any:
        """Resolve module ID with fallback policy.

        Policy: Try bundle first, fall back to environment/packages.

        Args:
            module_id: Module identifier (e.g., "provider-anthropic").
            source_hint: Optional hint for resolution.
            profile_hint: DEPRECATED - use source_hint instead.

        Returns:
            Module source.

        Raises:
            ModuleNotFoundError: If module not found anywhere.
        """
        hint = profile_hint if profile_hint is not None else source_hint

        # Try bundle first (primary source)
        try:
            return self._bundle.resolve(module_id, hint)
        except ModuleNotFoundError:
            pass  # Fall through to fallback resolver

        # Try fallback resolver
        try:
            result = self._fallback.resolve(module_id, hint)
            logger.debug(f"Resolved '{module_id}' from fallback")
            return result
        except ModuleResolutionError as e:
            logger.debug(f"Fallback failed for '{module_id}': {e}")

        # Neither worked - raise informative error
        available = list(getattr(self._bundle, "_paths", {}).keys())
        raise ModuleNotFoundError(
            f"Module '{module_id}' not found in bundle or fallback. "
            f"Bundle contains: {available}. "
            f"Ensure the module is included in the bundle or install the provider."
        )

    def get_module_source(self, module_id: str) -> str | None:
        """Get module source path as string.

        Args:
            module_id: Module identifier.

        Returns:
            String path to module, or None if not found.
        """
        # Check bundle first
        paths = getattr(self._bundle, "_paths", {})
        if module_id in paths:
            return str(paths[module_id])
        return None

    def __repr__(self) -> str:
        return f"AppModuleResolver(bundle={self._bundle}, fallback={self._fallback})"
