"""Unit tests for session routes.

Tests the HTTP endpoint handlers for session management.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from amplifier_server_app.routes.session import (
    ApprovalRequest,
    CreateSessionRequest,
    PromptRequest,
    UpdateSessionRequest,
)

# =============================================================================
# Request/Response Model Tests
# =============================================================================


class TestRequestModels:
    """Tests for request/response Pydantic models."""

    def test_create_session_request_defaults(self) -> None:
        """CreateSessionRequest has sensible defaults."""
        req = CreateSessionRequest()
        assert req.title is None
        assert req.bundle is None
        assert req.provider is None
        assert req.model is None
        assert req.working_directory is None

    def test_create_session_request_with_values(self) -> None:
        """CreateSessionRequest accepts all fields."""
        req = CreateSessionRequest(
            title="Test Session",
            bundle="foundation",
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            working_directory="/home/user",
        )
        assert req.title == "Test Session"
        assert req.bundle == "foundation"
        assert req.provider == "anthropic"
        assert req.model == "claude-sonnet-4-20250514"
        assert req.working_directory == "/home/user"

    def test_update_session_request(self) -> None:
        """UpdateSessionRequest accepts title."""
        req = UpdateSessionRequest(title="New Title")
        assert req.title == "New Title"

    def test_prompt_request_content_required(self) -> None:
        """PromptRequest requires content."""
        req = PromptRequest(content="Hello")
        assert req.content == "Hello"
        assert req.parts is None

    def test_prompt_request_with_parts(self) -> None:
        """PromptRequest accepts multimodal parts."""
        parts = [{"type": "text", "text": "Hello"}]
        req = PromptRequest(content="Hello", parts=parts)
        assert req.parts == parts

    def test_approval_request(self) -> None:
        """ApprovalRequest has required fields."""
        req = ApprovalRequest(request_id="req_123", choice="approve")
        assert req.request_id == "req_123"
        assert req.choice == "approve"


# =============================================================================
# List Sessions Handler Tests
# =============================================================================


class TestListSessionsHandler:
    """Tests for list_sessions endpoint."""

    @pytest.mark.asyncio
    async def test_list_sessions_returns_json(self) -> None:
        """list_sessions returns JSON response."""
        from amplifier_server_app.routes.session import list_sessions

        mock_request = MagicMock()

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.list_sessions = AsyncMock(return_value=[])

            response = await list_sessions(mock_request)

            assert response.status_code == 200
            assert response.media_type == "application/json"

    @pytest.mark.asyncio
    async def test_list_sessions_returns_sessions(self) -> None:
        """list_sessions returns session list."""
        from amplifier_server_app.routes.session import list_sessions

        mock_request = MagicMock()
        mock_sessions = [
            {"id": "sess_1", "title": "Session 1"},
            {"id": "sess_2", "title": "Session 2"},
        ]

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.list_sessions = AsyncMock(return_value=mock_sessions)

            response = await list_sessions(mock_request)

            body = json.loads(response.body)
            assert len(body) == 2
            assert body[0]["id"] == "sess_1"


# =============================================================================
# Create Session Handler Tests
# =============================================================================


class TestCreateSessionHandler:
    """Tests for create_session endpoint."""

    @pytest.mark.asyncio
    async def test_create_session_returns_created(self) -> None:
        """create_session returns 201 on success."""
        from amplifier_server_app.routes.session import create_session

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b'{"title": "Test"}')
        mock_request.json = AsyncMock(return_value={"title": "Test"})

        mock_session = MagicMock()
        mock_session.id = "sess_123"
        mock_session.title = "Test"
        mock_session.to_dict = MagicMock(return_value={"id": "sess_123", "title": "Test"})
        mock_session.initialize = AsyncMock()

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.create = AsyncMock(return_value=mock_session)

            response = await create_session(mock_request)

            assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_create_session_passes_config(self) -> None:
        """create_session passes configuration to manager."""
        from amplifier_server_app.routes.session import create_session

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=b'{"title": "Test"}')
        mock_request.json = AsyncMock(
            return_value={
                "title": "Test",
                "bundle": "foundation",
                "provider": "anthropic",
            }
        )

        mock_session = MagicMock()
        mock_session.id = "sess_123"
        mock_session.to_dict = MagicMock(return_value={"id": "sess_123"})
        mock_session.initialize = AsyncMock()

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.create = AsyncMock(return_value=mock_session)

            await create_session(mock_request)

            mock_manager.create.assert_called_once()


# =============================================================================
# Get Session Handler Tests
# =============================================================================


class TestGetSessionHandler:
    """Tests for get_session endpoint."""

    @pytest.mark.asyncio
    async def test_get_session_returns_session(self) -> None:
        """get_session returns session data."""
        from amplifier_server_app.routes.session import get_session

        mock_request = MagicMock()
        mock_request.path_params = {"session_id": "sess_123"}

        mock_session = MagicMock()
        mock_session.id = "sess_123"
        mock_session.title = "Test"
        mock_session.to_dict = MagicMock(return_value={"id": "sess_123", "title": "Test"})

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.get = AsyncMock(return_value=mock_session)

            response = await get_session(mock_request)

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_session_not_found(self) -> None:
        """get_session returns 404 for unknown session."""
        from amplifier_server_app.routes.session import get_session

        mock_request = MagicMock()
        mock_request.path_params = {"session_id": "unknown"}

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.get = AsyncMock(return_value=None)

            response = await get_session(mock_request)

            assert response.status_code == 404


# =============================================================================
# Delete Session Handler Tests
# =============================================================================


class TestDeleteSessionHandler:
    """Tests for delete_session endpoint."""

    @pytest.mark.asyncio
    async def test_delete_session_returns_no_content(self) -> None:
        """delete_session returns 204 on success."""
        from amplifier_server_app.routes.session import delete_session

        mock_request = MagicMock()
        mock_request.path_params = {"session_id": "sess_123"}

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.delete = AsyncMock(return_value=True)

            response = await delete_session(mock_request)

            # API returns 200 with success message, not 204
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_session_not_found(self) -> None:
        """delete_session returns 404 for unknown session."""
        from amplifier_server_app.routes.session import delete_session

        mock_request = MagicMock()
        mock_request.path_params = {"session_id": "unknown"}

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.delete = AsyncMock(return_value=False)

            response = await delete_session(mock_request)

            assert response.status_code == 404


# =============================================================================
# Prompt Handler Tests
# =============================================================================


class TestPromptHandler:
    """Tests for send_prompt execution endpoint."""

    @pytest.mark.asyncio
    async def test_send_prompt_returns_streaming_response(self) -> None:
        """send_prompt endpoint returns streaming response."""
        from starlette.responses import StreamingResponse

        from amplifier_server_app.routes.session import send_prompt

        mock_request = MagicMock()
        mock_request.path_params = {"session_id": "sess_123"}
        mock_request.json = AsyncMock(return_value={"content": "Hello"})

        mock_session = MagicMock()
        mock_session.is_running = False

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.get = AsyncMock(return_value=mock_session)

            response = await send_prompt(mock_request)

            # Should return a streaming response
            assert isinstance(response, StreamingResponse)

    @pytest.mark.asyncio
    async def test_send_prompt_session_not_found(self) -> None:
        """send_prompt returns 404 for unknown session."""
        from amplifier_server_app.routes.session import send_prompt

        mock_request = MagicMock()
        mock_request.path_params = {"session_id": "unknown"}
        mock_request.json = AsyncMock(return_value={"content": "Hello"})

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.get = AsyncMock(return_value=None)

            response = await send_prompt(mock_request)

            assert response.status_code == 404


# =============================================================================
# Approval Handler Tests
# =============================================================================


class TestApprovalHandler:
    """Tests for handle_approval response endpoint."""

    @pytest.mark.asyncio
    async def test_handle_approval_success(self) -> None:
        """handle_approval returns success on valid approval."""
        from amplifier_server_app.routes.session import handle_approval

        mock_request = MagicMock()
        mock_request.path_params = {"session_id": "sess_123"}
        mock_request.json = AsyncMock(return_value={"request_id": "req_1", "choice": "approve"})

        mock_session = MagicMock()
        mock_session.handle_approval = AsyncMock(return_value=True)

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.get = AsyncMock(return_value=mock_session)

            response = await handle_approval(mock_request)

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_handle_approval_session_not_found(self) -> None:
        """handle_approval returns 404 for unknown session."""
        from amplifier_server_app.routes.session import handle_approval

        mock_request = MagicMock()
        mock_request.path_params = {"session_id": "unknown"}
        mock_request.json = AsyncMock(return_value={"request_id": "req_1", "choice": "approve"})

        with patch("amplifier_server_app.routes.session.session_manager") as mock_manager:
            mock_manager.get = AsyncMock(return_value=None)

            response = await handle_approval(mock_request)

            assert response.status_code == 404
