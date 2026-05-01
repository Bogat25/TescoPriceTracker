"""User-facing alerts CRUD. All endpoints require a valid Keycloak Bearer JWT."""

from fastapi import APIRouter, Depends, HTTPException, status

from auth import current_user
from models import AlertListResponse, AlertOut, CreateAlertRequest
from services import alert_repo


router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", response_model=AlertListResponse)
async def list_alerts(user: dict = Depends(current_user)) -> AlertListResponse:
    docs = await alert_repo.list_for_user(user["sub"])
    return AlertListResponse(alerts=[AlertOut(**d) for d in docs])


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: CreateAlertRequest,
    user: dict = Depends(current_user),
) -> AlertOut:
    doc = await alert_repo.create(user["sub"], body.model_dump())
    return AlertOut(**doc)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(
    alert_id: str,
    user: dict = Depends(current_user),
) -> None:
    deleted = await alert_repo.delete(user["sub"], alert_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")
