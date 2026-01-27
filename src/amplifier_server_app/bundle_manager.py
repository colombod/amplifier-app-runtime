"""Bundle manager for Amplifier Server App.

Thin wrapper around amplifier-foundation's bundle system.
Provides bundle loading, preparation, and provider detection.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amplifier_foundation import Bundle, PreparedBundle
    from amplifier_foundation.registry import BundleRegistry

logger = logging.getLogger(__name__)


@dataclass
class BundleInfo:
    """Minimal info about a bundle for API responses."""

    name: str
    description: str = ""
    uri: str | None = None


class BundleManager:
    """Thin wrapper around amplifier-foundation's bundle system.

    Responsibilities (app-layer policy):
    - Provide registry instance
    - Compose provider credentials at runtime
    - Auto-detect providers from environment

    NOT responsible for (foundation handles):
    - Bundle discovery, loading, parsing
    - Module activation and resolution
    - Session creation internals
    """

    def __init__(self) -> None:
        """Initialize bundle manager."""
        self._registry: BundleRegistry | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize by importing foundation and creating registry."""
        if self._initialized:
            return

        try:
            from amplifier_foundation.registry import BundleRegistry

            self._registry = BundleRegistry()
            self._initialized = True
            logger.info("Bundle manager initialized with amplifier-foundation")

        except ImportError as e:
            logger.error(f"Failed to import amplifier-foundation: {e}")
            raise RuntimeError(
                "amplifier-foundation not available. "
                "Install with: pip install amplifier-foundation"
            ) from e

    @property
    def registry(self) -> "BundleRegistry":
        """Get the bundle registry. Must call initialize() first."""
        if not self._registry:
            raise RuntimeError("BundleManager not initialized. Call initialize() first.")
        return self._registry

    async def load_and_prepare(
        self,
        bundle_name: str,
        behaviors: list[str] | None = None,
        provider_config: dict[str, Any] | None = None,
        working_directory: Path | None = None,
    ) -> "PreparedBundle":
        """Load a bundle, compose behaviors, inject provider config, and prepare.

        Args:
            bundle_name: Bundle to load (e.g., "foundation", "amplifier-dev")
            behaviors: Optional behavior bundles to compose
            provider_config: Optional provider config to inject
            working_directory: Working directory for session (passed to create_session)

        Returns:
            PreparedBundle ready for create_session()
        """
        await self.initialize()

        from amplifier_foundation import Bundle
        from amplifier_foundation.registry import load_bundle

        # Load the base bundle
        bundle = await load_bundle(bundle_name, registry=self._registry)
        logger.info(f"Loaded bundle: {bundle_name}")

        # Compose with behaviors if specified
        if behaviors:
            for behavior_name in behaviors:
                # Behaviors are typically namespaced like "foundation:behaviors/streaming-ui"
                behavior_ref = behavior_name
                if ":" not in behavior_name and "/" not in behavior_name:
                    # Short name - assume foundation behavior
                    behavior_ref = f"foundation:behaviors/{behavior_name}"

                try:
                    behavior_bundle = await load_bundle(behavior_ref, registry=self._registry)
                    bundle = bundle.compose(behavior_bundle)
                    logger.info(f"Composed behavior: {behavior_name}")
                except Exception as e:
                    logger.warning(f"Failed to load behavior '{behavior_name}': {e}")

        # Enable debug for event visibility
        debug_bundle = Bundle(
            name="server-debug-config",
            version="1.0.0",
            session={"debug": True, "raw_debug": True},
        )
        bundle = bundle.compose(debug_bundle)

        # Compose with provider config if specified
        if provider_config:
            provider_bundle = Bundle(
                name="app-provider-config",
                version="1.0.0",
                providers=[provider_config],
            )
            bundle = bundle.compose(provider_bundle)
            logger.info(f"Injected provider config: {provider_config.get('module')}")
        else:
            # Auto-detect provider from environment
            provider_bundle = await self._auto_detect_provider()
            if provider_bundle:
                bundle = bundle.compose(provider_bundle)

        # Prepare the bundle
        prepared = await bundle.prepare()
        logger.info(f"Bundle prepared: {bundle_name}")

        return prepared

    async def _auto_detect_provider(self) -> "Bundle | None":
        """Auto-detect provider from environment variables.

        Returns:
            Provider Bundle if API key found, None otherwise.
        """
        from amplifier_foundation import Bundle

        # Check for Anthropic API key
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                provider = Bundle(
                    name="auto-provider-anthropic",
                    version="1.0.0",
                    providers=[
                        {
                            "module": "provider-anthropic",
                            "source": "git+https://github.com/microsoft/amplifier-module-provider-anthropic@main",
                            "config": {
                                "default_model": "claude-sonnet-4-5-20250514",
                                "debug": True,
                                "raw_debug": True,
                            },
                        }
                    ],
                )
                logger.info("Auto-detected Anthropic provider from environment")
                return provider
            except Exception as e:
                logger.warning(f"Failed to create Anthropic provider: {e}")

        # Check for OpenAI API key
        if os.getenv("OPENAI_API_KEY"):
            try:
                provider = Bundle(
                    name="auto-provider-openai",
                    version="1.0.0",
                    providers=[
                        {
                            "module": "provider-openai",
                            "source": "git+https://github.com/microsoft/amplifier-module-provider-openai@main",
                            "config": {
                                "default_model": "gpt-4o",
                                "debug": True,
                                "raw_debug": True,
                            },
                        }
                    ],
                )
                logger.info("Auto-detected OpenAI provider from environment")
                return provider
            except Exception as e:
                logger.warning(f"Failed to create OpenAI provider: {e}")

        logger.warning("No API key found in environment (ANTHROPIC_API_KEY or OPENAI_API_KEY)")
        return None

    async def list_bundles(self) -> list[BundleInfo]:
        """List available bundles.

        Returns:
            List of BundleInfo with name and description.
        """
        await self.initialize()

        bundles = [
            BundleInfo(name="foundation", description="Core foundation bundle with tools and agents"),
            BundleInfo(name="amplifier-dev", description="Bundle for Amplifier ecosystem development"),
        ]

        return bundles

    async def invalidate_cache(self) -> None:
        """Invalidate bundle/module cache.

        Called when module loading fails due to dependency issues.
        """
        try:
            # Clear the registry's cache
            if self._registry:
                if hasattr(self._registry, "clear_cache"):
                    self._registry.clear_cache()
                    logger.info("Cleared bundle registry cache")

            # Also clear foundation's module cache if available
            try:
                from amplifier_foundation.module_resolver import clear_module_cache

                clear_module_cache()
                logger.info("Cleared module resolver cache")
            except (ImportError, AttributeError):
                pass

        except Exception as e:
            logger.warning(f"Failed to invalidate cache: {e}")
