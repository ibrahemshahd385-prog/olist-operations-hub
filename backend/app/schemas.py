"""Shapes of the data the API accepts (validated automatically by FastAPI/Pydantic).

Pydantic checks types and simple ranges before our code even runs. Rules that
need the database (does this product exist? do payments add up?) are checked
in services/orders.py.
"""
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from .config import BRAZIL_STATES, MAX_INSTALLMENTS, MAX_QUANTITY_PER_LINE, PAYMENT_TYPES


class CustomerIn(BaseModel):
    # Either pick an existing customer (customer_unique_id) or give a new address.
    customer_unique_id: Optional[str] = None
    zip_code_prefix: Optional[str] = Field(None, description="5 digits, e.g. 01310")
    city: Optional[str] = None
    state: Optional[str] = None

    @field_validator("state")
    @classmethod
    def state_must_exist(cls, v):
        if v is not None and v.upper() not in BRAZIL_STATES:
            raise ValueError(f"'{v}' is not a Brazilian state code")
        return v.upper() if v else v

    @field_validator("zip_code_prefix")
    @classmethod
    def zip_five_digits(cls, v):
        if v is not None and not (v.isdigit() and len(v) == 5):
            raise ValueError("zip_code_prefix must be exactly 5 digits")
        return v


class OrderLineIn(BaseModel):
    product_id: str
    seller_id: str
    unit_price: float = Field(..., gt=0)
    quantity: int = Field(1, ge=1, le=MAX_QUANTITY_PER_LINE)
    freight_value: float = Field(..., ge=0, description="freight per unit, as in the dataset")


class PaymentIn(BaseModel):
    payment_type: str
    installments: int = Field(1, ge=1, le=MAX_INSTALLMENTS)
    value: float = Field(..., gt=0)

    @field_validator("payment_type")
    @classmethod
    def known_type(cls, v):
        if v not in PAYMENT_TYPES:
            raise ValueError(f"payment_type must be one of {PAYMENT_TYPES}")
        return v


class OrderCreate(BaseModel):
    customer: CustomerIn
    items: List[OrderLineIn] = Field(..., min_length=1)
    payments: List[PaymentIn] = Field(..., min_length=1)


class ActionIn(BaseModel):
    note: Optional[str] = None


class InvoiceIssueIn(BaseModel):
    seller_id: str


class QuoteLineIn(BaseModel):
    product_id: str
    seller_id: str
    unit_price: float = Field(..., gt=0)
    quantity: int = Field(1, ge=1, le=MAX_QUANTITY_PER_LINE)
    freight_value: Optional[float] = Field(None, ge=0)


class QuoteIn(BaseModel):
    """Ask the logistics models about an order before it is registered."""
    customer: CustomerIn
    items: List[QuoteLineIn] = Field(..., min_length=1)
    payment_types: List[str] = []
