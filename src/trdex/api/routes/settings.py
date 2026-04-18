"""Runtime configuration API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from trdex.api.app import verify_api_key
from trdex.services.runtime_config import (
    CREDENTIAL_KEYS,
    get_config_service,
    mask_credential,
)

router = APIRouter(prefix="/v1/settings", tags=["settings"])

VALID_CATEGORIES = {"credentials", "symbols", "thresholds", "scheduler", "feeds", "telegram", "integrations"}


class ConfigCategoryResponse(BaseModel):
    category: str
    values: dict[str, str]


class ConfigUpdateRequest(BaseModel):
    values: dict[str, str]


class ConfigAllResponse(BaseModel):
    categories: dict[str, dict[str, str]]


def _mask_category(category: str, values: dict[str, str]) -> dict[str, str]:
    """Mask credential values in API responses."""
    if category != "credentials":
        return values
    return {k: mask_credential(v) for k, v in values.items()}


@router.get("")
async def get_all_settings(
    _key: str = Depends(verify_api_key),
) -> ConfigAllResponse:
    """Return all config categories (credentials masked)."""
    svc = get_config_service()
    if svc is None:
        raise HTTPException(503, "Config service not initialised")
    all_cats = svc.get_all_categories()
    masked = {cat: _mask_category(cat, vals) for cat, vals in all_cats.items()}
    return ConfigAllResponse(categories=masked)


@router.get("/{category}")
async def get_category_settings(
    category: str,
    _key: str = Depends(verify_api_key),
) -> ConfigCategoryResponse:
    """Return all key-value pairs for a single category."""
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, f"Unknown category: {category}. Valid: {sorted(VALID_CATEGORIES)}")
    svc = get_config_service()
    if svc is None:
        raise HTTPException(503, "Config service not initialised")
    values = svc.get_category(category)
    return ConfigCategoryResponse(
        category=category,
        values=_mask_category(category, values),
    )


@router.put("/{category}")
async def update_category_settings(
    category: str,
    body: ConfigUpdateRequest,
    _key: str = Depends(verify_api_key),
) -> ConfigCategoryResponse:
    """Bulk upsert config values for a category. Fires hot-reload listeners."""
    if category not in VALID_CATEGORIES:
        raise HTTPException(400, f"Unknown category: {category}. Valid: {sorted(VALID_CATEGORIES)}")
    svc = get_config_service()
    if svc is None:
        raise HTTPException(503, "Config service not initialised")
    # Filter out empty values (user didn't touch the field)
    pairs = {k: v for k, v in body.values.items() if v}
    if not pairs:
        raise HTTPException(400, "No non-empty values provided")
    await svc.put_category(category, pairs)
    # Return updated values (masked for credentials)
    values = svc.get_category(category)
    return ConfigCategoryResponse(
        category=category,
        values=_mask_category(category, values),
    )
