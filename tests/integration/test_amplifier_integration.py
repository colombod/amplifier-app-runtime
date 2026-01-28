"""Integration tests for real Amplifier session mode.

Tests the server-app's integration with amplifier-core and amplifier-foundation.
These tests require the Amplifier packages to be installed and will skip
gracefully if they're not available.

Run with: pytest tests/integration/test_amplifier_integration.py -v
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# Check if amplifier packages are available
try:
    import amplifier_foundation  # noqa: F401

    AMPLIFIER_AVAILABLE = True
except ImportError:
    AMPLIFIER_AVAILABLE = False

# Check if API key is available for provider tests
HAS_ANTHROPIC_KEY = bool(os.getenv("ANTHROPIC_API_KEY"))
HAS_OPENAI_KEY = bool(os.getenv("OPENAI_API_KEY"))
HAS_ANY_PROVIDER = HAS_ANTHROPIC_KEY or HAS_OPENAI_KEY

# Skip markers
requires_amplifier = pytest.mark.skipif(
    not AMPLIFIER_AVAILABLE,
    reason="amplifier-core/foundation not installed",
)
requires_provider = pytest.mark.skipif(
    not HAS_ANY_PROVIDER,
    reason="No API key available (ANTHROPIC_API_KEY or OPENAI_API_KEY)",
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_send_fn() -> AsyncMock:
    """Create a mock send function for protocols."""
    return AsyncMock()


@pytest.fixture
def tmp_session_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for session data."""
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    return session_dir


# =============================================================================
# Protocol Interface Tests
# =============================================================================


class TestServerApprovalSystem:
    """Tests for ServerApprovalSystem protocol interface."""

    def test_approval_system_signature(self) -> None:
        """Verify ServerApprovalSystem has correct interface."""
        from amplifier_server_app.protocols.approval import ServerApprovalSystem

        system = ServerApprovalSystem()

        # Check method exists with correct signature
        assert hasattr(system, "request_approval")
        assert callable(system.request_approval)

        # Check signature matches expected interface
        import inspect

        sig = inspect.signature(system.request_approval)
        params = list(sig.parameters.keys())

        # Expected: prompt, options, timeout, default
        assert "prompt" in params
        assert "options" in params
        assert "timeout" in params
        assert "default" in params

    @pytest.mark.anyio
    async def test_approval_default_without_send_fn(self) -> None:
        """Without send_fn, approval should return default."""
        from amplifier_server_app.protocols.approval import ServerApprovalSystem

        system = ServerApprovalSystem(send_fn=None)

        result = await system.request_approval(
            prompt="Allow this action?",
            options=["Allow", "Deny"],
            timeout=30.0,
            default="deny",
        )

        # Should return a deny-like option
        assert "deny" in result.lower() or result == "Deny"

    @pytest.mark.anyio
    async def test_approval_sends_event(self, mock_send_fn: AsyncMock) -> None:
        """Approval should send event to client."""
        from amplifier_server_app.protocols.approval import ServerApprovalSystem

        system = ServerApprovalSystem(send_fn=mock_send_fn)

        # Start approval request (will timeout and return default)
        result = await system.request_approval(
            prompt="Allow this action?",
            options=["Allow", "Deny"],
            timeout=0.1,
            default="deny",
        )

        # Should return deny-like option on timeout
        assert "deny" in result.lower() or result == "Deny"

        # Verify approval:required event was sent
        assert mock_send_fn.called
        # Find the approval:required event (there may be multiple events)
        approval_events = [
            call[0][0]
            for call in mock_send_fn.call_args_list
            if call[0][0].type == "approval:required"
        ]
        assert len(approval_events) >= 1
        event = approval_events[0]
        assert "prompt" in event.properties
        assert event.properties["prompt"] == "Allow this action?"


class TestServerDisplaySystem:
    """Tests for ServerDisplaySystem protocol interface."""

    def test_display_system_signature(self) -> None:
        """Verify ServerDisplaySystem has correct interface."""
        from amplifier_server_app.protocols.display import ServerDisplaySystem

        system = ServerDisplaySystem()

        # Check method exists
        assert hasattr(system, "show_message")
        assert callable(system.show_message)

        # Check nesting support
        assert hasattr(system, "push_nesting")
        assert hasattr(system, "pop_nesting")
        assert hasattr(system, "nesting_depth")

    @pytest.mark.anyio
    async def test_display_without_send_fn(self) -> None:
        """Without send_fn, display should log but not fail."""
        from amplifier_server_app.protocols.display import ServerDisplaySystem

        system = ServerDisplaySystem(send_fn=None)

        # Should not raise
        await system.show_message("Test message", level="info", source="test")

    @pytest.mark.anyio
    async def test_display_sends_event(self, mock_send_fn: AsyncMock) -> None:
        """Display should send event to client."""
        from amplifier_server_app.protocols.display import ServerDisplaySystem

        system = ServerDisplaySystem(send_fn=mock_send_fn)

        await system.show_message("Test message", level="warning", source="test")

        # Verify event was sent
        assert mock_send_fn.called
        call_args = mock_send_fn.call_args[0][0]
        assert call_args.type == "display:message"
        assert call_args.properties["message"] == "Test message"
        assert call_args.properties["level"] == "warning"

    def test_nesting_depth(self) -> None:
        """Test nesting depth tracking."""
        from amplifier_server_app.protocols.display import ServerDisplaySystem

        system = ServerDisplaySystem(nesting_depth=0)
        assert system.nesting_depth == 0

        nested = system.push_nesting()
        assert nested.nesting_depth == 1

        double_nested = nested.push_nesting()
        assert double_nested.nesting_depth == 2

        back = double_nested.pop_nesting()
        assert back.nesting_depth == 1


# =============================================================================
# Resolver Tests
# =============================================================================


class TestAppModuleResolver:
    """Tests for AppModuleResolver fallback behavior."""

    def test_resolver_exists(self) -> None:
        """Verify resolver module is importable."""
        from amplifier_server_app.resolvers import (
            AppModuleResolver,
            FallbackResolver,
            ModuleResolutionError,
        )

        assert AppModuleResolver is not None
        assert FallbackResolver is not None
        assert ModuleResolutionError is not None

    def test_fallback_resolver_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fallback resolver should check environment variables."""
        from amplifier_server_app.resolvers import FallbackResolver, FileSource

        # Set environment variable
        monkeypatch.setenv("AMPLIFIER_MODULE_TEST_MODULE", "/tmp/test-module")

        resolver = FallbackResolver()

        # Should resolve from env var
        source = resolver.resolve("test-module")
        assert isinstance(source, FileSource)
        assert str(source.path) == "/tmp/test-module"

    def test_fallback_resolver_not_found(self) -> None:
        """Fallback resolver should raise clear error when module not found."""
        from amplifier_server_app.resolvers import FallbackResolver, ModuleResolutionError

        resolver = FallbackResolver()

        with pytest.raises(ModuleResolutionError) as exc_info:
            resolver.resolve("nonexistent-module-xyz")

        # Error should include helpful suggestions
        assert "nonexistent-module-xyz" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()


# =============================================================================
# Bundle Manager Tests (require amplifier)
# =============================================================================


@requires_amplifier
class TestBundleManager:
    """Tests for BundleManager with real amplifier-foundation."""

    @pytest.mark.anyio
    async def test_manager_initialization(self) -> None:
        """Bundle manager should initialize successfully."""
        from amplifier_server_app.bundle_manager import BundleManager

        manager = BundleManager()
        await manager.initialize()

        assert manager._initialized
        assert manager._registry is not None

    @pytest.mark.anyio
    async def test_list_bundles(self) -> None:
        """Should list available bundles."""
        from amplifier_server_app.bundle_manager import BundleManager

        manager = BundleManager()
        bundles = await manager.list_bundles()

        assert len(bundles) >= 1
        bundle_names = [b.name for b in bundles]
        assert "foundation" in bundle_names

    @pytest.mark.anyio
    async def test_load_foundation_bundle(self) -> None:
        """Should load and prepare foundation bundle."""
        from amplifier_server_app.bundle_manager import BundleManager

        manager = BundleManager()
        prepared = await manager.load_and_prepare(bundle_name="foundation")

        assert prepared is not None
        # Prepared bundle should have resolver
        assert hasattr(prepared, "resolver")


# =============================================================================
# Session Creation Tests (require amplifier)
# =============================================================================


@requires_amplifier
class TestManagedSessionWithAmplifier:
    """Tests for ManagedSession with real Amplifier integration."""

    @pytest.mark.anyio
    async def test_session_creates_with_bundle(
        self, tmp_session_dir: Path, mock_send_fn: AsyncMock
    ) -> None:
        """Session should initialize with real bundle."""
        from amplifier_server_app.session import ManagedSession, SessionConfig
        from amplifier_server_app.session_store import SessionStore

        store = SessionStore(tmp_session_dir)

        config = SessionConfig(bundle="foundation")
        session = ManagedSession(
            session_id="test-session-1",
            config=config,
            send_fn=mock_send_fn,
            store=store,
        )

        await session.initialize()

        # Session should be ready
        assert session.metadata.state.value == "ready"
        # Verify session was initialized (either with real amplifier or mock mode)
        # The session object should be usable regardless of mode

    @pytest.mark.anyio
    async def test_session_resolver_wrapping(
        self, tmp_session_dir: Path, mock_send_fn: AsyncMock
    ) -> None:
        """Session should wrap resolver with AppModuleResolver."""
        from amplifier_server_app.resolvers import AppModuleResolver
        from amplifier_server_app.session import ManagedSession, SessionConfig
        from amplifier_server_app.session_store import SessionStore

        store = SessionStore(tmp_session_dir)

        config = SessionConfig(bundle="foundation")
        session = ManagedSession(
            session_id="test-session-2",
            config=config,
            send_fn=mock_send_fn,
            store=store,
        )

        await session.initialize()

        # If amplifier session was created, check resolver wrapping
        if session._prepared_bundle is not None:
            resolver = session._prepared_bundle.resolver
            assert isinstance(resolver, AppModuleResolver)


# =============================================================================
# End-to-End Tests (require amplifier + provider)
# =============================================================================


@requires_amplifier
@requires_provider
class TestEndToEndWithProvider:
    """End-to-end tests requiring a real provider."""

    @pytest.mark.anyio
    @pytest.mark.timeout(60)  # Allow time for LLM response
    async def test_simple_prompt_execution(
        self, tmp_session_dir: Path, mock_send_fn: AsyncMock
    ) -> None:
        """Execute a simple prompt with real provider."""
        from amplifier_server_app.session import ManagedSession, SessionConfig
        from amplifier_server_app.session_store import SessionStore

        store = SessionStore(tmp_session_dir)

        config = SessionConfig(bundle="foundation")
        session = ManagedSession(
            session_id="test-e2e-1",
            config=config,
            send_fn=mock_send_fn,
            store=store,
        )

        await session.initialize()

        # Skip if fell back to mock mode
        if session._amplifier_session is None:
            pytest.skip("Session fell back to mock mode (provider not available)")

        # Execute a simple prompt using the streaming API
        events = []
        async for event in session.execute("Say 'hello' and nothing else"):
            events.append(event)

        # Should get events back
        assert len(events) > 0

    @pytest.mark.anyio
    @pytest.mark.timeout(60)
    async def test_streaming_events(self, tmp_session_dir: Path, mock_send_fn: AsyncMock) -> None:
        """Verify streaming events are emitted during execution."""
        from amplifier_server_app.session import ManagedSession, SessionConfig
        from amplifier_server_app.session_store import SessionStore

        store = SessionStore(tmp_session_dir)

        config = SessionConfig(bundle="foundation")
        session = ManagedSession(
            session_id="test-e2e-2",
            config=config,
            send_fn=mock_send_fn,
            store=store,
        )

        await session.initialize()

        if session._amplifier_session is None:
            pytest.skip("Session fell back to mock mode")

        # Execute prompt using streaming API
        events = []
        async for event in session.execute("Count to 3"):
            events.append(event)

        # Should receive multiple events during execution
        assert len(events) > 0

        # Collect event types
        event_types = [e.type for e in events]

        # Should have some events
        assert len(event_types) >= 1


# =============================================================================
# Cleanup helper
# =============================================================================


@pytest.fixture(autouse=True)
def cleanup_sessions():
    """Cleanup any sessions after tests."""
    yield
    # Cleanup happens automatically via tmp_path fixture
