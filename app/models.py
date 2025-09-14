from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database import Base

class Store(Base):
    __tablename__ = "stores"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=False, index=True)
    chain = Column(String(255), index=True)  # z.B. Migros, Coop, Aldi, Lidl
    address = Column(String(255))
    country = Column(String(2), default="CH")
    receipts = relationship("Receipt", back_populates="store")

class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id"), index=True)
    purchase_datetime = Column(DateTime, default=datetime.utcnow)
    raw_text = Column(Text)
    source_file = Column(String(512))  # Pfad zur Originaldatei
    ocr_engine = Column(String(64), default="tesseract")
    currency = Column(String(3), default="CHF")
    total = Column(Float, nullable=True)

    store = relationship("Store", back_populates="receipts")
    lines = relationship("LineItem", back_populates="receipt", cascade="all, delete-orphan")

class LineItem(Base):
    __tablename__ = "line_items"
    id = Column(Integer, primary_key=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), index=True)
    raw_name = Column(String(255), index=True)
    qty = Column(Float, default=1.0)
    unit_price = Column(Float, nullable=True)
    total_price = Column(Float, nullable=True)
    normalized_sku_id = Column(Integer, ForeignKey("normalized_products.id"), nullable=True)

    receipt = relationship("Receipt", back_populates="lines")
    normalized = relationship("NormalizedProduct")

class NormalizedProduct(Base):
    __tablename__ = "normalized_products"
    id = Column(Integer, primary_key=True)
    # Kettenübergreifende Normalisierung (für spätere Vergleiche)
    canonical_name = Column(String(255), index=True)
    brand_family = Column(String(255), index=True)  # z.B. "Budget", "Prix Garantie", "M-Budget", "Aldi Eigenmarke"
    category = Column(String(255), index=True)
