"""Unit tests for ACP content block conversion to Amplifier format.

Tests the multi-modal content handling in AmplifierAgentSession:
- Text content blocks
- Image content blocks with various MIME types
- Audio content blocks (unsupported)
- Embedded resource content blocks
- Resource link content blocks (unsupported)
- Mixed multi-modal content
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from acp.schema import (  # type: ignore[import-untyped]
    AudioContentBlock,
    BlobResourceContents,
    EmbeddedResourceContentBlock,
    ImageContentBlock,
    ResourceContentBlock,
    TextContentBlock,
    TextResourceContents,
)

from amplifier_app_runtime.acp.agent import AmplifierAgentSession


@pytest.fixture
def session() -> AmplifierAgentSession:
    """Create a minimal session for testing content conversion."""
    return AmplifierAgentSession(
        session_id="test-session",
        cwd="/tmp",
        bundle="test-bundle",
        conn=None,
        client_capabilities=None,
    )


class TestTextContentConversion:
    """Tests for text content block conversion."""

    def test_text_content_block_converts_correctly(self, session: AmplifierAgentSession) -> None:
        """TextContentBlock should convert to Amplifier text format."""
        blocks = [TextContentBlock(type="text", text="Hello, world!")]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 1
        assert amplifier_blocks[0] == {"type": "text", "text": "Hello, world!"}
        assert text_prompt == "Hello, world!"
        assert warnings == []

    def test_multiple_text_blocks_combine_into_prompt(self, session: AmplifierAgentSession) -> None:
        """Multiple text blocks should combine into a single prompt."""
        blocks = [
            TextContentBlock(type="text", text="First line"),
            TextContentBlock(type="text", text="Second line"),
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 2
        assert text_prompt == "First line\nSecond line"
        assert warnings == []

    def test_dict_style_text_block_converts_correctly(self, session: AmplifierAgentSession) -> None:
        """Dict-style text blocks should also convert correctly."""
        blocks: list[Any] = [{"type": "text", "text": "Dict-style text"}]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 1
        assert amplifier_blocks[0] == {"type": "text", "text": "Dict-style text"}
        assert text_prompt == "Dict-style text"


class TestImageContentConversion:
    """Tests for image content block conversion."""

    def test_png_image_converts_correctly(self, session: AmplifierAgentSession) -> None:
        """PNG images should convert to Amplifier image format."""
        blocks = [
            ImageContentBlock(
                type="image",
                mimeType="image/png",
                data="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            )
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 1
        assert amplifier_blocks[0]["type"] == "image"
        assert amplifier_blocks[0]["source"]["type"] == "base64"
        assert amplifier_blocks[0]["source"]["media_type"] == "image/png"
        assert "iVBORw0KGgo" in amplifier_blocks[0]["source"]["data"]
        assert warnings == []

    def test_jpeg_image_converts_correctly(self, session: AmplifierAgentSession) -> None:
        """JPEG images should convert correctly."""
        blocks = [
            ImageContentBlock(
                type="image",
                mimeType="image/jpeg",
                data="base64data",
            )
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 1
        assert amplifier_blocks[0]["source"]["media_type"] == "image/jpeg"

    def test_gif_image_converts_correctly(self, session: AmplifierAgentSession) -> None:
        """GIF images should convert correctly."""
        blocks = [
            ImageContentBlock(
                type="image",
                mimeType="image/gif",
                data="base64data",
            )
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 1
        assert amplifier_blocks[0]["source"]["media_type"] == "image/gif"

    def test_webp_image_converts_correctly(self, session: AmplifierAgentSession) -> None:
        """WebP images should convert correctly."""
        blocks = [
            ImageContentBlock(
                type="image",
                mimeType="image/webp",
                data="base64data",
            )
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 1
        assert amplifier_blocks[0]["source"]["media_type"] == "image/webp"

    def test_unsupported_image_type_generates_warning(self, session: AmplifierAgentSession) -> None:
        """Unsupported image types should generate a warning."""
        blocks = [
            ImageContentBlock(
                type="image",
                mimeType="image/bmp",
                data="base64data",
            )
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 0
        assert len(warnings) == 1
        assert "Unsupported image type" in warnings[0]
        assert "image/bmp" in warnings[0]

    def test_image_without_data_is_skipped(self, session: AmplifierAgentSession) -> None:
        """Images without data should be skipped with warning."""
        block = MagicMock(spec=ImageContentBlock)
        block.type = "image"
        block.mimeType = "image/png"
        block.data = None

        result = session._convert_image_block(block)

        assert result is None


class TestAudioContentConversion:
    """Tests for audio content block handling (unsupported)."""

    def test_audio_content_generates_warning(self, session: AmplifierAgentSession) -> None:
        """Audio content should generate a warning message."""
        blocks = [
            AudioContentBlock(
                type="audio",
                mimeType="audio/wav",
                data="base64audiodata",
            )
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 0
        assert len(warnings) == 1
        assert "Audio content is not currently supported" in warnings[0]


class TestEmbeddedResourceConversion:
    """Tests for embedded resource content block conversion."""

    def test_text_resource_converts_with_uri_context(self, session: AmplifierAgentSession) -> None:
        """Text resources should include URI context."""
        resource = TextResourceContents(
            uri="file:///path/to/code.py",
            text="def hello():\n    pass",
            mimeType="text/x-python",
        )
        blocks = [EmbeddedResourceContentBlock(type="resource", resource=resource)]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 1
        assert amplifier_blocks[0]["type"] == "text"
        assert "[Resource: file:///path/to/code.py]" in amplifier_blocks[0]["text"]
        assert "def hello():" in amplifier_blocks[0]["text"]
        assert warnings == []

    def test_text_resource_without_uri(self, session: AmplifierAgentSession) -> None:
        """Text resources without URI should still work."""
        resource = TextResourceContents(
            uri="",
            text="Plain text content",
        )
        blocks = [EmbeddedResourceContentBlock(type="resource", resource=resource)]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 1
        assert amplifier_blocks[0] == {"type": "text", "text": "Plain text content"}

    def test_blob_image_resource_converts_to_image(self, session: AmplifierAgentSession) -> None:
        """Blob resources with image MIME type should convert to images."""
        resource = BlobResourceContents(
            uri="file:///path/to/image.png",
            blob="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            mimeType="image/png",
        )
        blocks = [EmbeddedResourceContentBlock(type="resource", resource=resource)]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 1
        assert amplifier_blocks[0]["type"] == "image"
        assert amplifier_blocks[0]["source"]["media_type"] == "image/png"

    def test_blob_resource_with_unsupported_type_is_skipped(
        self, session: AmplifierAgentSession
    ) -> None:
        """Blob resources with unsupported MIME types should be skipped."""
        resource = BlobResourceContents(
            uri="file:///path/to/file.pdf",
            blob="pdfdata",
            mimeType="application/pdf",
        )
        blocks = [EmbeddedResourceContentBlock(type="resource", resource=resource)]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        # PDF is not supported, so no blocks converted
        assert len(amplifier_blocks) == 0


class TestResourceLinkConversion:
    """Tests for resource link content block handling (unsupported)."""

    def test_resource_link_generates_warning(self, session: AmplifierAgentSession) -> None:
        """Resource links should generate a warning about not being fetchable."""
        blocks = [
            ResourceContentBlock(
                type="resource_link",
                uri="https://example.com/file.txt",
                name="external-file",
            )
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 0
        assert len(warnings) == 1
        assert "External resource links cannot be fetched" in warnings[0]


class TestMixedContentConversion:
    """Tests for mixed multi-modal content conversion."""

    def test_text_and_image_combined(self, session: AmplifierAgentSession) -> None:
        """Text and image content should both be converted."""
        blocks = [
            TextContentBlock(type="text", text="What's in this image?"),
            ImageContentBlock(
                type="image",
                mimeType="image/png",
                data="base64imagedata",
            ),
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 2
        assert amplifier_blocks[0] == {"type": "text", "text": "What's in this image?"}
        assert amplifier_blocks[1]["type"] == "image"
        assert text_prompt == "What's in this image?"
        assert warnings == []

    def test_multiple_images_with_text(self, session: AmplifierAgentSession) -> None:
        """Multiple images with text should all be converted."""
        blocks = [
            TextContentBlock(type="text", text="Compare these images:"),
            ImageContentBlock(type="image", mimeType="image/png", data="image1data"),
            ImageContentBlock(type="image", mimeType="image/jpeg", data="image2data"),
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 3
        assert amplifier_blocks[0]["type"] == "text"
        assert amplifier_blocks[1]["type"] == "image"
        assert amplifier_blocks[2]["type"] == "image"

    def test_mixed_supported_and_unsupported_content(self, session: AmplifierAgentSession) -> None:
        """Mixed content should convert supported types and warn for unsupported."""
        blocks = [
            TextContentBlock(type="text", text="Process this:"),
            ImageContentBlock(type="image", mimeType="image/png", data="imagedata"),
            AudioContentBlock(type="audio", mimeType="audio/wav", data="audiodata"),
            ResourceContentBlock(type="resource_link", uri="https://example.com", name="link"),
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        # Only text and image should be converted
        assert len(amplifier_blocks) == 2
        assert amplifier_blocks[0]["type"] == "text"
        assert amplifier_blocks[1]["type"] == "image"

        # Should have warnings for audio and resource link
        assert len(warnings) == 2
        assert any("Audio" in w for w in warnings)
        assert any("External resource" in w for w in warnings)


class TestEmptyContentHandling:
    """Tests for edge cases with empty or minimal content."""

    def test_empty_content_list(self, session: AmplifierAgentSession) -> None:
        """Empty content list should return fallback prompt."""
        blocks: list[Any] = []

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 0
        assert text_prompt == "Please provide content with text or images."

    def test_only_unsupported_content(self, session: AmplifierAgentSession) -> None:
        """Only unsupported content should return fallback prompt."""
        blocks = [
            AudioContentBlock(type="audio", mimeType="audio/wav", data="audiodata"),
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 0
        assert text_prompt == "Please provide content with text or images."
        assert len(warnings) == 1

    def test_only_image_no_text(self, session: AmplifierAgentSession) -> None:
        """Image-only content should NOT use fallback (image is valid content)."""
        blocks = [
            ImageContentBlock(type="image", mimeType="image/png", data="imagedata"),
        ]

        amplifier_blocks, text_prompt, warnings = session._convert_acp_to_amplifier_blocks(blocks)

        assert len(amplifier_blocks) == 1
        # Empty text prompt is OK when there's an image
        assert text_prompt == ""


class TestConvertImageBlock:
    """Tests for the _convert_image_block helper method."""

    def test_returns_none_for_missing_mime_type(self, session: AmplifierAgentSession) -> None:
        """Should return None if MIME type is missing."""
        block = MagicMock()
        block.mimeType = None
        block.mime_type = None
        block.data = "somedata"

        result = session._convert_image_block(block)

        assert result is None

    def test_returns_none_for_missing_data(self, session: AmplifierAgentSession) -> None:
        """Should return None if data is missing."""
        block = MagicMock()
        block.mimeType = "image/png"
        block.data = None

        result = session._convert_image_block(block)

        assert result is None

    def test_handles_alternate_mime_type_attribute(self, session: AmplifierAgentSession) -> None:
        """Should handle both mimeType and mime_type attributes."""
        block = MagicMock()
        block.mimeType = None
        block.mime_type = "image/jpeg"
        block.data = "imagedata"

        result = session._convert_image_block(block)

        assert result is not None
        assert result["source"]["media_type"] == "image/jpeg"


class TestConvertEmbeddedResource:
    """Tests for the _convert_embedded_resource helper method."""

    def test_returns_none_for_missing_resource(self, session: AmplifierAgentSession) -> None:
        """Should return None if resource is missing."""
        block = MagicMock()
        block.resource = None

        result = session._convert_embedded_resource(block)

        assert result is None

    def test_returns_none_for_blob_without_mime_type(self, session: AmplifierAgentSession) -> None:
        """Should return None for blob without MIME type."""
        block = MagicMock()
        block.resource = MagicMock()
        block.resource.text = None
        block.resource.blob = "blobdata"
        block.resource.mimeType = None
        block.resource.mime_type = None
        block.resource.uri = ""

        result = session._convert_embedded_resource(block)

        assert result is None
