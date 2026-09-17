"""Pydantic request/response models for the alert service."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


AlertType = Literal["TARGET_PRICE", "PERCENTAGE_DROP"]


class CreateAlertRequest(BaseModel):
    # Either a bare Tesco tpnc (older clients, the browser extension) or a
    # target: an offer reference (``auchan:678170``) or a group (``g:54026193``).
    productId: Optional[str] = Field(default=None, min_length=1)
    target: Optional[str] = Field(default=None, min_length=1)
    # Stores a group alert watches; default every enabled store.
    stores: Optional[list[str]] = Field(default=None, max_length=10)
    alertType: AlertType
    targetPrice: Optional[float] = None
    dropPercentage: Optional[float] = None
    basePriceAtCreation: Optional[float] = None

    @model_validator(mode="after")
    def _check_required_for_type(self):
        if not (self.target or self.productId):
            raise ValueError("productId or target is required")
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
    target: str
    stores: list[str]
    # True while every store the alert watches is switched off.
    paused: bool = False
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


class EmailPreference(BaseModel):
    emailEnabled: bool


class PriceDrop(BaseModel):
    # Offer reference (``auchan:678170``); a bare tpnc is read as a Tesco offer.
    productId: str = Field(min_length=1)
    store: Optional[str] = Field(default=None, max_length=32)
    groupId: Optional[str] = Field(default=None, max_length=64)
    newPrice: float = Field(gt=0)
    oldPrice: Optional[float] = Field(default=None, gt=0)
    productName: Optional[str] = None

    @field_validator("productId")
    @classmethod
    def _coerce_id(cls, v: str) -> str:
        return v.strip()


class TriggerPayload(BaseModel):
    drops: list[PriceDrop]
    # One logical trigger, e.g. the scraper's business date. A scraper that could
    # not record delivery resends it; the key stops those digests going out twice.
    runKey: Optional[str] = Field(default=None, min_length=1, max_length=64)


class TriggerResponse(BaseModel):
    processed: int
    triggered: int
    emailsSent: int
    skipped: int
    duplicate: bool = False
