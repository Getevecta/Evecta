"""Regression: an is_enabled=False override must revoke, not grant."""
from __future__ import annotations

from types import SimpleNamespace

from app.services.permission_service import (
    calculate_final_permissions,
    enabled_permission_names,
    grouped_permissions_from_final,
    resolve_permission_grant,
)


def test_override_false_revokes_role_permission():
    enabled, overridden = resolve_permission_grant(
        in_role=True,
        override_enabled=False,
    )
    assert enabled is False
    assert overridden is True


def test_override_true_grants_permission_not_in_role():
    enabled, overridden = resolve_permission_grant(
        in_role=False,
        override_enabled=True,
    )
    assert enabled is True
    assert overridden is True


def test_no_override_uses_role_default():
    enabled, overridden = resolve_permission_grant(
        in_role=True,
        override_enabled=None,
    )
    assert enabled is True
    assert overridden is False


def test_neither_role_nor_override_is_denied():
    enabled, overridden = resolve_permission_grant(
        in_role=False,
        override_enabled=None,
    )
    assert enabled is False
    assert overridden is False


def _perm(id_, name):
    return SimpleNamespace(id=id_, name=name)


def _override(perm_id, is_enabled, name):
    return SimpleNamespace(
        permission_id=perm_id,
        is_enabled=is_enabled,
        permission=SimpleNamespace(name=name),
    )


def test_calculate_final_permissions_honors_disabled_override():
    manage = _perm("p1", "manage_roles")
    user = SimpleNamespace(
        role_obj=SimpleNamespace(permissions=[manage]),
        permission_overrides=[_override("p1", False, "manage_roles")],
    )
    user.final_permissions = calculate_final_permissions(user)

    assert user.final_permissions["manage_roles"]["final"] is False
    assert "manage_roles" not in enabled_permission_names(user)


def test_calculate_final_permissions_keeps_role_default_without_override():
    manage = _perm("p1", "manage_roles")
    user = SimpleNamespace(
        role_obj=SimpleNamespace(permissions=[manage]),
        permission_overrides=[],
    )
    user.final_permissions = calculate_final_permissions(user)

    assert user.final_permissions["manage_roles"]["final"] is True
    assert enabled_permission_names(user) == {"manage_roles"}


def test_require_permission_style_check_fails_closed_without_final_permissions():
    user = SimpleNamespace(is_superuser=False)
    assert enabled_permission_names(user) == set()


def test_grouped_permissions_match_calculate_final_permissions():
    manage = _perm("p1", "manage_roles")
    view = _perm("p2", "view_users")
    user = SimpleNamespace(
        role_obj=SimpleNamespace(permissions=[manage, view]),
        permission_overrides=[_override("p1", False, "manage_roles")],
    )
    final = calculate_final_permissions(user)
    grouped = grouped_permissions_from_final(
        [
            SimpleNamespace(id="p1", name="manage_roles", description="", group="Admin"),
            SimpleNamespace(id="p2", name="view_users", description="", group="Admin"),
            SimpleNamespace(id="p3", name="other", description="", group="Admin"),
        ],
        final,
    )
    by_name = {p["name"]: p for p in grouped["Admin"]["permissions"]}
    assert by_name["manage_roles"]["final_enabled"] is False
    assert by_name["manage_roles"]["overridden"] is True
    assert by_name["view_users"]["final_enabled"] is True
    assert by_name["other"]["final_enabled"] is False
    assert grouped["Admin"]["enabled_count"] == 1
