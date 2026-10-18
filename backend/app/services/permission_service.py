from typing import Dict, Optional, Set
from app.models.user import User
from fastapi import HTTPException, status


def resolve_permission_grant(
    *,
    in_role: bool,
    override_enabled: Optional[bool],
) -> tuple[bool, bool]:
    """Decide whether a permission is granted.

    An override row always wins, including ``is_enabled=False`` (explicit revoke).
    No override falls back to the role default. Neither role nor override → denied.

    Returns ``(final_enabled, overridden)``.
    """
    if override_enabled is not None:
        return bool(override_enabled), True
    return bool(in_role), False


def permission_is_granted(final_permissions: Dict[str, Dict], permission_name: str) -> bool:
    """Single grant check used by route guards and any UI derived from the same map."""
    meta = final_permissions.get(permission_name) or {}
    return bool(meta.get("final"))


def enabled_permission_names(user: User) -> Set[str]:
    """Permission names the user is actually allowed to use (role + overrides)."""
    final = getattr(user, "final_permissions", None) or {}
    return {name for name in final if permission_is_granted(final, name)}


def grouped_permissions_from_final(
    all_permissions,
    final_permissions: Dict[str, Dict],
) -> Dict[str, Dict]:
    """Admin UI grouping derived from calculate_final_permissions — not a second grant algorithm."""
    grouped: Dict[str, Dict] = {}
    for perm in all_permissions:
        group = perm.group or "General"
        if group not in grouped:
            grouped[group] = {
                "group_name": group,
                "enabled_count": 0,
                "total_count": 0,
                "permissions": [],
            }

        meta = final_permissions.get(perm.name) or {}
        final_enabled = bool(meta.get("final"))
        overridden = meta.get("override") is not None
        role_default = bool(meta.get("role_default"))

        if final_enabled:
            grouped[group]["enabled_count"] += 1
        grouped[group]["total_count"] += 1
        grouped[group]["permissions"].append({
            "id": str(perm.id),
            "name": perm.name,
            "description": perm.description,
            "final_enabled": final_enabled,
            "role_default": role_default,
            "overridden": overridden,
        })
    return grouped


def calculate_final_permissions(user: User) -> Dict[str, Dict]:
    """
    Merge Role permissions + User overrides → Final permissions.
    Returns structure ready for API & UI.
    """
    try:
        final_permissions: Dict[str, Dict] = {}

        # Load Role Permissions (defaults)
        try:
            role_permissions = {}
            if user.role_obj:
                for perm in user.role_obj.permissions:
                    role_permissions[perm.id] = perm.name
                    final_permissions[perm.name] = {
                        "permission_id": perm.id,
                        "role_default": True,
                        "override": None,
                        "final": True,
                        "label": "Role Default",
                    }
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error processing role permissions"
            )

        # Load User Overrides
        try:
            override_map = {}
            for override in user.permission_overrides:
                override_map[override.permission_id] = {
                    "is_enabled": override.is_enabled,
                    "permission_name": override.permission.name,
                    "permission_id": override.permission_id,
                }
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error processing user permission overrides"
            )

        # Merge Overrides with Role Defaults
        try:
            for perm_id, override in override_map.items():
                perm_name = override["permission_name"]
                in_role = perm_id in role_permissions
                final_enabled, _overridden = resolve_permission_grant(
                    in_role=in_role,
                    override_enabled=override["is_enabled"],
                )
                final_permissions[perm_name] = {
                    "permission_id": perm_id,
                    "role_default": in_role,
                    "override": True if final_enabled else False,
                    "final": final_enabled,
                    "label": "Custom Enabled" if final_enabled else "Custom Disabled",
                }

        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error merging role permissions with user overrides"
            )

        return final_permissions

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again."
        )
