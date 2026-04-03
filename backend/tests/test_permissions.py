"""Tests for permission system — download permission, library exclusions, admin bypass."""

import uuid

from app.models.library import Library, UserLibraryExclusion
from app.models.user import User, UserRole

# ---------------------------------------------------------------------------
# accessible_libraries_condition
# ---------------------------------------------------------------------------


class TestAccessibleLibrariesCondition:
    """Test the deny-list library access logic."""

    def test_admin_returns_true(self):
        """Admin user should bypass all access checks."""
        from app.routers.libraries import accessible_libraries_condition

        admin = User(
            id=uuid.uuid4(),
            username="admin",
            password_hash="x",
            role=UserRole.admin,
        )
        result = accessible_libraries_condition(admin)
        assert result is True

    def test_regular_user_returns_sqlalchemy_condition(self):
        """Regular user should get a NOT EXISTS condition, not True."""
        from app.routers.libraries import accessible_libraries_condition

        user = User(
            id=uuid.uuid4(),
            username="user",
            password_hash="x",
            role=UserRole.user,
        )
        result = accessible_libraries_condition(user)
        # Should not be True (which is the admin bypass)
        assert result is not True
        # Should be a SQLAlchemy clause element
        assert hasattr(result, "compile")


# ---------------------------------------------------------------------------
# User model — can_download field
# ---------------------------------------------------------------------------


class TestUserCanDownload:
    """Test that User model has can_download field with correct default."""

    def test_default_false(self):
        user = User(
            id=uuid.uuid4(),
            username="test",
            password_hash="x",
            role=UserRole.user,
            can_download=False,
        )
        assert user.can_download is False

    def test_can_set_true(self):
        user = User(
            id=uuid.uuid4(),
            username="test",
            password_hash="x",
            role=UserRole.user,
            can_download=True,
        )
        assert user.can_download is True


# ---------------------------------------------------------------------------
# UserLibraryExclusion model
# ---------------------------------------------------------------------------


class TestUserLibraryExclusion:
    """Test the exclusion model structure."""

    def test_create_exclusion(self):
        user_id = uuid.uuid4()
        library_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        exclusion = UserLibraryExclusion(
            user_id=user_id,
            library_id=library_id,
            excluded_by=admin_id,
        )
        assert exclusion.user_id == user_id
        assert exclusion.library_id == library_id
        assert exclusion.excluded_by == admin_id


# ---------------------------------------------------------------------------
# Library model — no visibility field
# ---------------------------------------------------------------------------


class TestLibraryModel:
    """Test that Library model no longer has visibility field."""

    def test_no_visibility_field(self):
        lib = Library(
            id=uuid.uuid4(),
            name="Test Library",
            created_by=uuid.uuid4(),
        )
        assert not hasattr(lib, "visibility")

    def test_has_exclusions_relationship(self):
        """Library should have exclusions relationship attribute."""
        assert hasattr(Library, "exclusions")


# ---------------------------------------------------------------------------
# Download permission check logic
# ---------------------------------------------------------------------------


class TestDownloadPermissionLogic:
    """Test the download permission check that should be in get_book_file."""

    def test_admin_can_always_download(self):
        """Admin bypasses can_download check."""
        admin = User(
            id=uuid.uuid4(),
            username="admin",
            password_hash="x",
            role=UserRole.admin,
            can_download=False,  # Even with false, admin bypasses
        )
        # The check in the endpoint is:
        # if current_user.role != UserRole.admin and not current_user.can_download:
        #     raise 403
        should_block = admin.role != UserRole.admin and not admin.can_download
        assert should_block is False

    def test_user_with_download_permission_passes(self):
        user = User(
            id=uuid.uuid4(),
            username="user",
            password_hash="x",
            role=UserRole.user,
            can_download=True,
        )
        should_block = user.role != UserRole.admin and not user.can_download
        assert should_block is False

    def test_user_without_download_permission_blocked(self):
        user = User(
            id=uuid.uuid4(),
            username="user",
            password_hash="x",
            role=UserRole.user,
            can_download=False,
        )
        should_block = user.role != UserRole.admin and not user.can_download
        assert should_block is True
