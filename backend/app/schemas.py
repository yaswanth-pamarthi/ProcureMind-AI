from datetime import date
from typing import Literal
from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field, model_validator, field_validator
from decimal import Decimal


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


DEFAULT_WEIGHTS = {"price": 30, "quality": 20, "delivery": 20, "compliance": 15, "contract": 15}


class Login(BaseModel):
    email: str
    password: str


class Register(Login):
    pass


class VendorIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    country: str = "India"
    category: str = "IT equipment"
    compliance_status: Literal["compliant", "conditional", "failed"] = "compliant"
    mandatory_failure: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"


class PerformanceIn(BaseModel):
    value: float = Field(ge=0, le=100)
    period: str
    source: str = Field(min_length=3)


class ItemIn(BaseModel):
    description: str = Field(min_length=3)
    quantity: int = Field(gt=0)
    unit: str = "piece"
    target_price: float = Field(gt=0)


class RFQIn(BaseModel):
    number: str = Field(min_length=3)
    title: str = Field(min_length=3)
    budget: float = Field(gt=0)
    currency: str = Field(pattern="^[A-Z]{3}$", default="INR")
    due_date: date
    weights_json: dict[str, float] = Field(default_factory=lambda: DEFAULT_WEIGHTS.copy())
    items: list[ItemIn] = Field(min_length=1)

    @model_validator(mode="after")
    def weights(self):
        if (
            set(self.weights_json) != set(DEFAULT_WEIGHTS)
            or any(v < 0 for v in self.weights_json.values())
            or abs(sum(self.weights_json.values()) - 100) > 1e-6
        ):
            raise ValueError("Weights must contain five factors and sum to 100")
        return self


class SubmissionIn(BaseModel):
    vendor_id: str


class StatusIn(BaseModel):
    status: Literal["DRAFT", "OPEN", "ANALYZING", "REVIEW", "APPROVED", "REJECTED"]


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "override"]
    reason: str = Field(min_length=5, max_length=2000)
    vendor_id: str | None = None

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class Quotation(BaseModel):
    currency: str = Field(pattern="^[A-Z]{3}$")
    total: float = Field(gt=0)
    unit_price: float = Field(gt=0)
    quantity: int = Field(gt=0)
    tax: float = Field(ge=0, le=100)
    delivery_days: int = Field(gt=0)
    payment: str
    warranty_months: int = Field(gt=0)
    evidence: dict

    @model_validator(mode="after")
    def arithmetic(self):
        expected = Decimal(str(self.unit_price)) * self.quantity * (1 + Decimal(str(self.tax)) / 100)
        if abs(expected - Decimal(str(self.total))) > Decimal("0.01"):
            raise ValueError("Line-item arithmetic does not reconcile with total")
        return self
