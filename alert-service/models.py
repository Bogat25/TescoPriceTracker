"""Pydantic request/response models for the alert service."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


AlertType = Literal["TARGET_PRICE", "PERCENTAGE_DROP"]


class CreateAlertRequest(BaseModel):
    productId: str = Field(min_length=1)
    alertType: AlertType
    targetPrice: Optional[float] = None
    dropPercentage: Optional[float] = None
    basePriceAtCreation: Optional[float] = None

    @model_validator(mode="after")
    def _check_required_for_type(self):
        if self.alertType == "TARGET_PRICE":
            if self.targetPrice is None or self.targetPrice <= 0:
                raise ValueError("targetPrice (>0) is required for TARGET_PRICE alerts")
        elif self.alertType == "PERCENTAGE_DROP":
            if self.dropPercentage is None or not (0 < self.dropPercentage <= 100):
                raise ValueError("dropPercentage (0<x<=100) is required for PERCENTAGE_DROP alerts")
            if self.basePriceAtCreation is None or self.basePriceAtCreation <= 0:
                raise ValueError("basePriceAtCreation (>0) is required for PERCENTAGE_DROP alerts")
        return self


class AlertOut(BaseModel):
    id: str
    userId: str
    productId: str
    alertType: AlertType
    targetPrice: Optional[float] = None
    dropPercentage: Optional[float] = None
    basePriceAtCreation: Optional[float] = None
    enabled: bool
    createdAt: datetime


class AlertListResponse(BaseModel):
    alerts: list[AlertOut]


class ToggleAlertRequest(BaseModel):
    enabled: bool


class PriceDrop(BaseModel):
    productId: str = Field(min_length=1)
    newPrice: float = Field(gt=0)
    oldPrice: Optional[float] = Field(default=None, gt=0)
    productName: Optional[str] = None

    @field_validator("productId")
    @classmethod
    def _coerce_id(cls, v: str) -> str:
        return v.strip()


class TriggerPayload(BaseModel):
    drops: list[PriceDrop]


class TriggerResponse(BaseModel):
    processed: int
    triggered: int
    emailsSent: int
    skipped: int
