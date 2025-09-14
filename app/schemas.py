from __future__ import annotations

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class LineItemIn(BaseModel):
    raw_name: str
    qty: float | None = 1.0
    unit_price: float | None = None
    total_price: float | None = None

class ReceiptOut(BaseModel):
    id: int
    store_id: int | None
    purchase_datetime: datetime
    source_file: str
    raw_text: str
    total: float | None

    class Config:
        from_attributes = True