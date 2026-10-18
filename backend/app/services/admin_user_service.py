from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from app.models.user import User
from app.models.role import Role
from app.utils.jwt import hash_password
from app.services.permission_override_service import (
    update_user_overrides,
    clear_user_overrides,
)
from app.services.effective_permission_service import get_effective_permissions
from app.services.user_service import get_user_by_email
from app.models.user_permission_override import UserPermissionOverride
from app.models.refresh_token import RefreshToken
from app.core.plans import DEFAULT_PLAN, PLANS, subscription_credit_amounts
from app.services.credit_service import apply_subscription_renewal, grant_plan_credits
from app.services.token_service import revoke_all_user_tokens
from app.services.admin_device_trust import revoke_all_admin_device_trust_for_user
import logging

logger = logging.getLogger(__name__)

PLAN_RANK = {"free": 0, "starter": 1, "growth": 2, "scale": 3}


async def admin_set_user_plan(
    session: AsyncSession,
    user_id: str,
    plan: str,
    plan_billing_interval: str | None = "month",
) -> dict:
    """
    Admin complimentary plan change (no Stripe checkout).

    Upgrades add the new plan's subscription credits; downgrades / moves to free
    replace the subscription bucket with the target allowance (same rules as
    billing confirm). Top-up balances are left alone.
    """
    plan_key = (plan or "").strip().lower()
    if plan_key not in PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan. Choose one of: {', '.join(PLANS.keys())}",
        )

    interval = (plan_billing_interval or "month").strip().lower()
    if interval not in ("month", "year"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="plan_billing_interval must be 'month' or 'year'.",
        )
    if plan_key == DEFAULT_PLAN:
        interval = "month"

    try:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    except SQLAlchemyError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while loading user",
        )

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old_plan = (user.plan or DEFAULT_PLAN).strip().lower()
    old_interval = (getattr(user, "plan_billing_interval", None) or "month").strip().lower()

    if old_plan == plan_key and old_interval == interval:
        return {
            "id": str(user.id),
            "email": user.email,
            "plan": user.plan,
            "plan_billing_interval": getattr(user, "plan_billing_interval", None),
            "changed": False,
            "message": "User is already on this plan.",
        }

    user.plan = plan_key
    user.plan_billing_interval = None if plan_key == DEFAULT_PLAN else interval
    user.subscription_cancel_at = None

    if plan_key == DEFAULT_PLAN:
        new_credits = dict(PLANS[DEFAULT_PLAN]["credits"])
    else:
        new_credits = subscription_credit_amounts(plan_key, interval)

    description = f"Admin plan change: {old_plan} → {plan_key}"
    try:
        if PLAN_RANK.get(plan_key, 0) < PLAN_RANK.get(old_plan, 0) or plan_key == DEFAULT_PLAN:
            await apply_subscription_renewal(
                session, user.id, new_credits, description, commit=False
            )
        else:
            await grant_plan_credits(
                session, user.id, new_credits, description, commit=False
            )
        await session.commit()
        await session.refresh(user)
    except HTTPException:
        raise
    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user plan. Please try again.",
        )

    return {
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "plan": user.plan,
        "plan_billing_interval": getattr(user, "plan_billing_interval", None),
        "previous_plan": old_plan,
        "credits_granted": new_credits,
        "changed": True,
        "message": f"Plan updated from {old_plan} to {plan_key}.",
    }

async def admin_update_user(session: AsyncSession, user_id: str, data):
    try:
        # 1. Load user
        try:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(status_code=500, detail="Database error while loading user")

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # 2. Email update
        if data.email:
            try:
                data.email = data.email.strip().lower()
                existing = await get_user_by_email(session, data.email)
            except SQLAlchemyError:
                await session.rollback()
                raise HTTPException(status_code=500, detail="Database error validating email")

            if existing and existing.id != user.id:
                raise HTTPException(status_code=400, detail="Email already exists")

            user.email = data.email

        # 3. Username update (not globally unique; email is)
        if data.username:
            user.username = data.username.strip()

        # 4. Full name
        if data.full_name:
            user.full_name = data.full_name

        # 5. Role update
        if data.role_id:
            try:
                result_role = await session.execute(select(Role).where(Role.id == data.role_id))
                role = result_role.scalar_one_or_none()
            except SQLAlchemyError:
                await session.rollback()
                raise HTTPException(status_code=500, detail="Database error validating role")

            if not role:
                raise HTTPException(status_code=404, detail="Invalid role ID")

            from app.services.admin_bootstrap import SOLE_ADMIN_EMAIL

            if (role.name or "").lower() == "admin":
                target_email = (data.email or user.email or "").strip().lower()
                if target_email != SOLE_ADMIN_EMAIL:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Only {SOLE_ADMIN_EMAIL} may hold the admin role.",
                    )

            user.role_id = data.role_id

            # Clear overrides when role changes (optional rule)
            try:
                await clear_user_overrides(session, user_id)
            except Exception:
                await session.rollback()
                raise HTTPException(status_code=500, detail="Failed to clear user overrides")

        # 6. Password update
        if data.password:
            try:
                user.hashed_password = hash_password(data.password)
            except Exception:
                raise HTTPException(status_code=500, detail="Failed to hash password")

        # 7. Active / inactive — disabling must kill live sessions
        became_inactive = False
        if data.is_active is not None:
            became_inactive = bool(user.is_active) and data.is_active is False
            user.is_active = data.is_active

        # 8. Profile fields
        for field in ["department", "location", "website", "bio", "profile_image"]:
            if getattr(data, field) is not None:
                setattr(user, field, getattr(data, field))

        # 9. Permission overrides
        if data.override_permission_ids is not None:
            try:
                await update_user_overrides(session, user_id, data.override_permission_ids)
            except SQLAlchemyError:
                await session.rollback()
                raise HTTPException(status_code=500, detail="Database error updating permission overrides")
            except Exception:
                await session.rollback()
                raise HTTPException(status_code=500, detail="Failed to update permission overrides")

        # 10. Save user
        try:
            await session.commit()
            await session.refresh(user)
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(status_code=500, detail="Failed to save user changes")

        if became_inactive:
            try:
                await revoke_all_user_tokens(session, user.id)
            except Exception:
                logger.exception("Failed to revoke refresh tokens for disabled user %s", user_id)
            try:
                await revoke_all_admin_device_trust_for_user(str(user.id))
            except Exception:
                logger.exception("Failed to revoke admin device trust for disabled user %s", user_id)

        # 11. Load final permissions
        try:
            effective_permissions = await get_effective_permissions(session, user_id)
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to load effective permissions")

        # Prepare user for response
        response_user = {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "email_verified": user.email_verified,
            "role_id": user.role_id,
            "department": user.department,
            "location": user.location,
            "website": user.website,
            "bio": user.bio,
            "profile_image": user.profile_image,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }

        return response_user, effective_permissions

    except HTTPException:
        # re-raise clean HTTP exceptions
        raise

    except Exception as e:
        # catch-all fallback
        await session.rollback()
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")


async def admin_hard_delete_user(session: AsyncSession, user_id: str):
    try:
        # Fetch user
        try:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error while fetching user"
            )

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Delete overrides
        try:
            await session.execute(
                delete(UserPermissionOverride)
                .where(UserPermissionOverride.user_id == user_id)
            )
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error deleting permission overrides"
            )

        # Delete refresh tokens (optional but recommended)
        try:
            await session.execute(
                delete(RefreshToken).where(RefreshToken.user_id == user_id)
            )
        except Exception:
            pass  # intentional: ignore if model not used

        try:
            await revoke_all_admin_device_trust_for_user(str(user.id))
        except Exception:
            logger.exception("Failed to revoke admin device trust for deleted user %s", user_id)

        # Delete user
        try:
            await session.execute(delete(User).where(User.id == user_id))
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error deleting user"
            )

        # Commit changes
        try:
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to commit delete operation"
            )

        return {
            "message": "User permanently deleted",
            "deleted_user_id": user_id
        }

    except HTTPException:
        # Pass through clean HTTP exceptions
        raise

    except Exception as e:
        # Catch-all fallback
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again."
        )


