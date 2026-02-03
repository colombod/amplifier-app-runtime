"""ACP to Amplifier content block conversion.

This module handles the conversion of ACP content blocks (text, image, audio,
embedded resources) to Amplifier's internal format.

Extracted from agent.py to improve maintainability and testability.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from acp.schema import (  # type: ignore[import-untyped]
    AudioContentBlock,
    EmbeddedResourceContentBlock,
    ImageContentBlock,
    ResourceContentBlock,
    TextContentBlock,
)

logger = logging.getLogger(__name__)


@dataclass
class ConversionResult:
    """Result of converting ACP content blocks to Amplifier format.

    Attributes:
        blocks: List of Amplifier-compatible content blocks
        text_prompt: Extracted text to use as the prompt
        warnings: List of warning messages for unsupported content
        has_images: Whether the result contains image blocks
    """

    blocks: list[dict[str, Any]] = field(default_factory=list)
    text_prompt: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        """Check if result contains image blocks."""
        return any(b.get("type") == "image" for b in self.blocks)

    @property
    def has_multimodal(self) -> bool:
        """Check if result contains multi-modal content (images)."""
        return self.has_images


@dataclass
class AcpToAmplifierContentConverter:
    """Converts ACP content blocks to Amplifier format.

    This class encapsulates the content conversion logic, making it easier
    to test and maintain separately from the session management code.

    Supported content types:
    - TextContentBlock -> {"type": "text", "text": "..."}
    - ImageContentBlock -> {"type": "image", "source": {...}}
    - EmbeddedResourceContentBlock -> text or image block
    - AudioContentBlock -> NOT SUPPORTED (warning generated)
    - ResourceContentBlock -> NOT SUPPORTED (warning generated)

    Usage:
        converter = AcpToAmplifierContentConverter()
        result = converter.convert(acp_blocks)
        if result.warnings:
            # Handle warnings about unsupported content
        amplifier_blocks = result.blocks
    """

    # Supported image MIME types
    supported_image_types: frozenset[str] = field(
        default=frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"}),
        repr=False,
    )

    def convert(self, blocks: list[Any]) -> ConversionResult:
        """Convert ACP content blocks to Amplifier format.

        Args:
            blocks: List of ACP content blocks

        Returns:
            ConversionResult with converted blocks, text prompt, and warnings
        """
        amplifier_blocks: list[dict[str, Any]] = []
        text_parts: list[str] = []
        warnings: list[str] = []

        for block in blocks:
            self._process_block(block, amplifier_blocks, text_parts, warnings)

        # Build text prompt from all text parts
        text_prompt = "\n".join(text_parts).strip()

        # Fallback if no content
        if not text_prompt and not any(b.get("type") == "image" for b in amplifier_blocks):
            text_prompt = "Please provide content with text or images."

        return ConversionResult(
            blocks=amplifier_blocks,
            text_prompt=text_prompt,
            warnings=warnings,
        )

    def _process_block(
        self,
        block: Any,
        amplifier_blocks: list[dict[str, Any]],
        text_parts: list[str],
        warnings: list[str],
    ) -> None:
        """Process a single ACP content block.

        Args:
            block: ACP content block to process
            amplifier_blocks: List to append converted blocks to
            text_parts: List to append text parts to
            warnings: List to append warnings to
        """
        # Handle TextContentBlock
        if isinstance(block, TextContentBlock):
            text_parts.append(block.text)
            amplifier_blocks.append({"type": "text", "text": block.text})

        # Handle dict-style text block
        elif isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            text_parts.append(text)
            amplifier_blocks.append({"type": "text", "text": text})

        # Handle ImageContentBlock
        elif isinstance(block, ImageContentBlock):
            converted = self._convert_image_block(block)
            if converted:
                amplifier_blocks.append(converted)
            else:
                mime_type = getattr(block, "mimeType", None) or getattr(
                    block, "mime_type", "unknown"
                )
                warnings.append(
                    f"Unsupported image type: {mime_type}. "
                    f"Supported types: {', '.join(sorted(self.supported_image_types))}"
                )

        # Handle AudioContentBlock (not supported)
        elif isinstance(block, AudioContentBlock):
            warnings.append("Audio content is not currently supported.")

        # Handle EmbeddedResourceContentBlock
        elif isinstance(block, EmbeddedResourceContentBlock):
            converted = self._convert_embedded_resource(block)
            if converted:
                amplifier_blocks.append(converted)
                # Also extract text for the prompt if it's a text resource
                if converted.get("type") == "text":
                    text_parts.append(converted.get("text", ""))

        # Handle ResourceContentBlock (external URI - not supported)
        elif isinstance(block, ResourceContentBlock):
            warnings.append(
                "External resource links cannot be fetched. Please embed content directly."
            )

        # Handle generic object with type attribute
        elif hasattr(block, "type"):
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text = getattr(block, "text", "")
                text_parts.append(text)
                amplifier_blocks.append({"type": "text", "text": text})
            else:
                logger.debug(f"Skipping unsupported block type: {block_type}")

    def _convert_image_block(self, block: ImageContentBlock) -> dict[str, Any] | None:
        """Convert ACP ImageContentBlock to Amplifier image format.

        Args:
            block: ACP ImageContentBlock with data and mimeType

        Returns:
            Amplifier image block or None if unsupported type
        """
        # Get MIME type - handle both attribute styles
        mime_type = getattr(block, "mimeType", None) or getattr(block, "mime_type", None)
        if not mime_type:
            return None

        # Check if supported
        if mime_type not in self.supported_image_types:
            return None

        # Get base64 data
        data = getattr(block, "data", None)
        if not data:
            return None

        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": data,
            },
        }

    def _convert_embedded_resource(
        self, block: EmbeddedResourceContentBlock
    ) -> dict[str, Any] | None:
        """Convert embedded resource to text or image block.

        Args:
            block: ACP EmbeddedResourceContentBlock with resource data

        Returns:
            Amplifier-compatible block (text or image) or None if unsupported
        """
        resource = getattr(block, "resource", None)
        if not resource:
            return None

        # Get URI for context
        uri = getattr(resource, "uri", "") or ""

        # Check if it's a text resource
        text = getattr(resource, "text", None)
        if text is not None:
            # Include URI context if available
            if uri:
                return {"type": "text", "text": f"[Resource: {uri}]\n{text}"}
            return {"type": "text", "text": text}

        # Check if it's a blob resource (potentially an image)
        blob = getattr(resource, "blob", None)
        if blob:
            mime_type = getattr(resource, "mimeType", None) or getattr(resource, "mime_type", None)
            if mime_type and mime_type in self.supported_image_types:
                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": blob,
                    },
                }

        return None
