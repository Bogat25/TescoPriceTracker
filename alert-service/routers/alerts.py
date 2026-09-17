"""User-facing alerts CRUD. All endpoints require a valid Keycloak Bearer JWT."""

from fastapi import APIRouter, Depends, HTTPException, status

from auth import current_user
from models import AlertListResponse, AlertOut, CreateAlertRequest, EmailPreference, ToggleAlertRequest
from services import alert_repo
import store_state
import targets


router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


# Both "" and "/" are registered so the bare-collection endpoint works whether
# the upstream caller (nginx, YARP, curl) sends a trailing slash or not. With
# redirect_slashes disabled at the app level, FastAPI no longer normalises them
# automatically.
@router.get("", response_model=AlertListResponse, include_in_schema=False)
@router.get("/", response_model=AlertListResponse)
async def list_alerts(user: dict = Depends(current_user)) -> AlertListResponse:
    docs = await alert_repo.list_for_user(user["sub"])
    enabled = await store_state.enabled_store_ids()
    return AlertListResponse(alerts=[_out(d, enabled) for d in docs])


def _out(doc: dict, enabled: set[str]) -> AlertOut:
    return AlertOut(**doc, paused=not any(store in enabled for store in doc["stores"]))


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED, include_in_schema=False)
@router.post("/", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: CreateAlertRequest,
    user: dict = Depends(current_user),
) -> AlertOut:
    enabled = await store_state.enabled_store_ids()
    try:
        target, product_id = targets.normalize(body.target or body.productId)
        stores = targets.resolve_stores(target, body.stores, enabled)
    except targets.InvalidTarget as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if not any(store in enabled for store in stores):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the selected stores are not available")
    payload = body.model_dump(exclude={"target", "stores", "productId"})
    payload.update(target=target, productId=product_id, stores=stores)
    doc = await alert_repo.create(user["sub"], payload)
    return _out(doc, enabled)


# ── Literal-path routes FIRST ────────────────────────────────────────────────
# /prefs must be defined BEFORE /{alert_id} so FastAPI (Starlette) doesn't
# treat "prefs" as a path parameter value when matching PATCH /prefs.

@router.get("/prefs", response_model=EmailPreference)
async def get_email_prefs(user: dict = Depends(current_user)) -> EmailPreference:
    """Return the current user's email notification preference."""
    enabled = await alert_repo.get_email_preference(user["sub"])
    return EmailPreference(emailEnabled=enabled)


@router.patch("/prefs", response_model=EmailPreference)
async def set_email_prefs(
    body: EmailPreference,
    user: dict = Depends(current_user),
) -> EmailPreference:
    """Update the current user's email notification preference."""
    enabled = await alert_repo.set_email_preference(user["sub"], body.emailEnabled)
    return EmailPreference(emailEnabled=enabled)


# ── Parameterised-path routes AFTER ──────────────────────────────────────────

@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: str,
    user: dict = Depends(current_user),
) -> None:
    deleted = await alert_repo.delete(user["sub"], alert_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")


@router.patch("/{alert_id}/toggle", response_model=AlertOut)
async def toggle_alert(
    alert_id: str,
    body: ToggleAlertRequest,
    user: dict = Depends(current_user),
) -> AlertOut:
    doc = await alert_repo.toggle(user["sub"], alert_id, body.enabled)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")
    return _out(doc, await store_state.enabled_store_ids())
