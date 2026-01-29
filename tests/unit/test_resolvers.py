"""Unit tests for resolvers module.

Tests the app-layer module resolution with fallback policy.
Minimal mocking - tests real code paths where possible.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from amplifier_app_runtime.resolvers import (
    AppModuleResolver,
    FallbackResolver,
    FileSource,
    GitSource,
    ModuleResolutionError,
    PackageSource,
)

# =============================================================================
# FileSource Tests
# =============================================================================


class TestFileSource:
    """Tests for FileSource - local filesystem resolution."""

    def test_resolve_existing_directory(self, tmp_path: Path) -> None:
        """FileSource resolves to existing directory."""
        source = FileSource(tmp_path)
        result = source.resolve()
        assert result == tmp_path
        assert result.is_dir()

    def test_resolve_with_file_uri(self, tmp_path: Path) -> None:
        """FileSource strips file:// prefix."""
        source = FileSource(f"file://{tmp_path}")
        result = source.resolve()
        assert result == tmp_path

    def test_resolve_nonexistent_raises(self) -> None:
        """FileSource raises for nonexistent path."""
        source = FileSource("/nonexistent/path/to/module")
        with pytest.raises(ModuleResolutionError, match="not found"):
            source.resolve()

    def test_resolve_file_not_directory_raises(self, tmp_path: Path) -> None:
        """FileSource raises if path is file, not directory."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("content")

        source = FileSource(file_path)
        with pytest.raises(ModuleResolutionError, match="not a directory"):
            source.resolve()

    def test_repr(self, tmp_path: Path) -> None:
        """FileSource repr shows path."""
        source = FileSource(tmp_path)
        assert "FileSource" in repr(source)
        assert str(tmp_path) in repr(source)

    def test_resolve_relative_path(self) -> None:
        """FileSource resolves relative paths to absolute."""
        source = FileSource(".")
        result = source.resolve()
        assert result.is_absolute()
        assert result.is_dir()


# =============================================================================
# PackageSource Tests
# =============================================================================


class TestPackageSource:
    """Tests for PackageSource - installed package resolution."""

    def test_resolve_installed_package(self) -> None:
        """PackageSource resolves installed package."""
        # pytest is definitely installed
        source = PackageSource("pytest")
        result = source.resolve()
        assert result.exists()
        assert result.is_dir()

    def test_resolve_nonexistent_package_raises(self) -> None:
        """PackageSource raises for non-installed package."""
        source = PackageSource("nonexistent-package-xyz-12345")
        with pytest.raises(ModuleResolutionError, match="not installed"):
            source.resolve()

    def test_repr(self) -> None:
        """PackageSource repr shows package name."""
        source = PackageSource("my-package")
        assert "PackageSource" in repr(source)
        assert "my-package" in repr(source)


# =============================================================================
# GitSource Tests
# =============================================================================


class TestGitSource:
    """Tests for GitSource - git repository resolution."""

    def test_repr(self) -> None:
        """GitSource repr shows URI."""
        uri = "git+https://github.com/org/repo@main"
        source = GitSource(uri)
        assert "GitSource" in repr(source)
        assert uri in repr(source)

    def test_uri_stored(self) -> None:
        """GitSource stores the URI."""
        uri = "git+https://github.com/org/repo@main"
        source = GitSource(uri)
        assert source.uri == uri


# =============================================================================
# FallbackResolver Tests
# =============================================================================


class TestFallbackResolver:
    """Tests for FallbackResolver - environment and package fallback."""

    def test_resolve_from_environment_variable(self, tmp_path: Path) -> None:
        """FallbackResolver uses environment variable first."""
        resolver = FallbackResolver()
        env_key = "AMPLIFIER_MODULE_TEST_MODULE"

        with patch.dict(os.environ, {env_key: str(tmp_path)}):
            result = resolver.resolve("test-module")

        assert isinstance(result, FileSource)
        assert result.path == tmp_path

    def test_resolve_env_var_git_source(self) -> None:
        """FallbackResolver parses git URI from env var."""
        resolver = FallbackResolver()
        env_key = "AMPLIFIER_MODULE_MY_MODULE"
        git_uri = "git+https://github.com/org/repo@main"

        with patch.dict(os.environ, {env_key: git_uri}):
            result = resolver.resolve("my-module")

        assert isinstance(result, GitSource)
        assert result.uri == git_uri

    def test_resolve_env_var_package_source(self) -> None:
        """FallbackResolver parses package name from env var."""
        resolver = FallbackResolver()
        env_key = "AMPLIFIER_MODULE_MY_MODULE"

        with patch.dict(os.environ, {env_key: "some-package"}):
            result = resolver.resolve("my-module")

        assert isinstance(result, PackageSource)
        assert result.package_name == "some-package"

    def test_resolve_from_source_hint_git(self) -> None:
        """FallbackResolver uses source hint when no env var."""
        resolver = FallbackResolver()
        git_uri = "git+https://github.com/org/repo@main"

        result = resolver.resolve("some-module", source_hint=git_uri)

        assert isinstance(result, GitSource)
        assert result.uri == git_uri

    def test_resolve_from_source_hint_file(self, tmp_path: Path) -> None:
        """FallbackResolver parses file path from source hint."""
        resolver = FallbackResolver()

        result = resolver.resolve("some-module", source_hint=str(tmp_path))

        assert isinstance(result, FileSource)

    def test_resolve_installed_package(self) -> None:
        """FallbackResolver falls back to installed package."""
        resolver = FallbackResolver()

        # pytest is installed
        result = resolver.resolve("pytest")

        assert isinstance(result, PackageSource)
        assert result.package_name == "pytest"

    def test_resolve_convention_name(self) -> None:
        """FallbackResolver tries amplifier-module-<id> convention."""
        resolver = FallbackResolver()

        # This should fail since amplifier-module-nonexistent isn't installed
        # but we can verify the error message mentions the convention
        with pytest.raises(ModuleResolutionError) as exc_info:
            resolver.resolve("nonexistent-module-xyz")

        assert "amplifier-module-nonexistent-module-xyz" in str(exc_info.value)

    def test_resolve_not_found_error_message(self) -> None:
        """FallbackResolver provides helpful error message."""
        resolver = FallbackResolver()

        with pytest.raises(ModuleResolutionError) as exc_info:
            resolver.resolve("nonexistent-xyz")

        error_msg = str(exc_info.value)
        assert "not found" in error_msg.lower()
        assert "AMPLIFIER_MODULE_NONEXISTENT_XYZ" in error_msg  # env var hint
        assert "Suggestions" in error_msg

    def test_parse_source_file_uri(self, tmp_path: Path) -> None:
        """_parse_source handles file:// URIs."""
        resolver = FallbackResolver()
        result = resolver._parse_source(f"file://{tmp_path}")
        assert isinstance(result, FileSource)

    def test_parse_source_absolute_path(self, tmp_path: Path) -> None:
        """_parse_source handles absolute paths."""
        resolver = FallbackResolver()
        result = resolver._parse_source(str(tmp_path))
        assert isinstance(result, FileSource)

    def test_parse_source_relative_path(self) -> None:
        """_parse_source handles relative paths."""
        resolver = FallbackResolver()
        result = resolver._parse_source("./local/path")
        assert isinstance(result, FileSource)

    def test_parse_source_git_uri(self) -> None:
        """_parse_source handles git+ URIs."""
        resolver = FallbackResolver()
        result = resolver._parse_source("git+https://github.com/org/repo")
        assert isinstance(result, GitSource)

    def test_parse_source_package_name(self) -> None:
        """_parse_source defaults to PackageSource."""
        resolver = FallbackResolver()
        result = resolver._parse_source("some-package-name")
        assert isinstance(result, PackageSource)


# =============================================================================
# AppModuleResolver Tests
# =============================================================================


class TestAppModuleResolver:
    """Tests for AppModuleResolver - bundle + fallback composition."""

    def test_resolve_from_bundle_first(self) -> None:
        """AppModuleResolver tries bundle resolver first."""

        # Mock bundle resolver that succeeds
        class MockBundleResolver:
            def resolve(self, module_id, hint=None):
                return Path("/bundle/path")

        resolver = AppModuleResolver(
            bundle_resolver=MockBundleResolver(),
            fallback_resolver=FallbackResolver(),
        )

        result = resolver.resolve("some-module")
        assert result == Path("/bundle/path")

    def test_resolve_falls_back_on_bundle_not_found(self, tmp_path: Path) -> None:
        """AppModuleResolver uses fallback when bundle doesn't have module."""

        # Mock bundle resolver that fails
        class MockBundleResolver:
            _paths = {}

            def resolve(self, module_id, hint=None):
                raise ModuleNotFoundError(f"Not in bundle: {module_id}")

        resolver = AppModuleResolver(
            bundle_resolver=MockBundleResolver(),
            fallback_resolver=FallbackResolver(),
        )

        # Set up environment variable fallback
        with patch.dict(os.environ, {"AMPLIFIER_MODULE_MY_MODULE": str(tmp_path)}):
            result = resolver.resolve("my-module")

        # Should get FileSource from fallback
        assert isinstance(result, FileSource)
        assert result.path == tmp_path

    def test_resolve_raises_when_both_fail(self) -> None:
        """AppModuleResolver raises when both bundle and fallback fail."""

        class MockBundleResolver:
            _paths = {}

            def resolve(self, module_id, hint=None):
                raise ModuleNotFoundError(f"Not in bundle: {module_id}")

        resolver = AppModuleResolver(
            bundle_resolver=MockBundleResolver(),
            fallback_resolver=FallbackResolver(),
        )

        with pytest.raises(ModuleNotFoundError, match="not found"):
            resolver.resolve("completely-nonexistent-module-xyz")

    def test_resolve_passes_hint_to_bundle(self) -> None:
        """AppModuleResolver passes hint to bundle resolver."""
        received_hints = []

        class MockBundleResolver:
            def resolve(self, module_id, hint=None):
                received_hints.append(hint)
                return Path("/bundle/path")

        resolver = AppModuleResolver(bundle_resolver=MockBundleResolver())
        resolver.resolve("module", source_hint="my-hint")

        assert received_hints == ["my-hint"]

    def test_resolve_profile_hint_deprecated(self) -> None:
        """AppModuleResolver supports deprecated profile_hint parameter."""
        received_hints = []

        class MockBundleResolver:
            def resolve(self, module_id, hint=None):
                received_hints.append(hint)
                return Path("/bundle/path")

        resolver = AppModuleResolver(bundle_resolver=MockBundleResolver())
        resolver.resolve("module", profile_hint="profile-hint")

        assert received_hints == ["profile-hint"]

    def test_get_module_source_from_bundle(self) -> None:
        """get_module_source returns path from bundle."""

        class MockBundleResolver:
            _paths = {"my-module": Path("/bundle/my-module")}

        resolver = AppModuleResolver(bundle_resolver=MockBundleResolver())
        result = resolver.get_module_source("my-module")

        assert result == "/bundle/my-module"

    def test_get_module_source_not_found(self) -> None:
        """get_module_source returns None when not in bundle."""

        class MockBundleResolver:
            _paths = {}

        resolver = AppModuleResolver(bundle_resolver=MockBundleResolver())
        result = resolver.get_module_source("nonexistent")

        assert result is None

    def test_repr(self) -> None:
        """AppModuleResolver repr shows components."""

        class MockBundleResolver:
            pass

        resolver = AppModuleResolver(bundle_resolver=MockBundleResolver())
        repr_str = repr(resolver)

        assert "AppModuleResolver" in repr_str
        assert "bundle=" in repr_str
        assert "fallback=" in repr_str

    def test_default_fallback_resolver(self) -> None:
        """AppModuleResolver creates default FallbackResolver."""

        class MockBundleResolver:
            pass

        resolver = AppModuleResolver(bundle_resolver=MockBundleResolver())

        assert resolver._fallback is not None
        assert isinstance(resolver._fallback, FallbackResolver)
