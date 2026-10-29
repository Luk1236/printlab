"""Kunden-Stamm: Adressbuch für Angebote und Rechnungen (leichtgewichtig).

Angebote/Rechnungen behalten ihre Kopie von Kunde und Anschrift — hier liegt
nur das Adressbuch darunter. Löschen ändert frühere Belege nicht.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.customer import Customer
from backend.app.models.user import User

router = APIRouter(prefix="/customers", tags=["customers"])

MAX_CUSTOMERS = 500


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    address: str = Field(default="", max_length=240)
    email: str = Field(default="", max_length=80)
    phone: str = Field(default="", max_length=40)
    note: str | None = Field(default=None, max_length=400)


class CustomerOut(CustomerIn):
    id: int


@router.get("/", response_model=list[CustomerOut])
async def list_customers(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
    db: AsyncSession = Depends(get_db),
):
    """Alle Kunden alphabetisch."""
    rows = await db.scalars(select(Customer).order_by(func.lower(Customer.name)))
    return list(rows)


@router.post("/", response_model=CustomerOut)
async def create_customer(
    payload: CustomerIn,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
    db: AsyncSession = Depends(get_db),
):
    """Kunden anlegen; doppelte Namen werden abgelehnt (Adressbuch, keine Reihung)."""
    count = (await db.execute(select(func.count()).select_from(Customer))).scalar_one()
    if count >= MAX_CUSTOMERS:
        raise HTTPException(400, "Es gibt schon die maximale Zahl an Kunden (500).")
    existing = await db.scalar(select(Customer).where(func.lower(Customer.name) == payload.name.lower()))
    if existing is not None:
        raise HTTPException(400, f"Kunde „{existing.name}“ existiert bereits.")
    entry = Customer(name=payload.name.strip(), **payload.model_dump(exclude={"name"}))
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: int,
    payload: CustomerIn,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
    db: AsyncSession = Depends(get_db),
):
    """Kundendaten ändern."""
    entry = await db.get(Customer, customer_id)
    if entry is None:
        raise HTTPException(404, "Kunde nicht gefunden.")
    other = await db.scalar(
        select(Customer).where(func.lower(Customer.name) == payload.name.lower(), Customer.id != customer_id)
    )
    if other is not None:
        raise HTTPException(400, f"Kunde „{other.name}“ existiert bereits.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, key, value)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
    db: AsyncSession = Depends(get_db),
):
    """Kunden entfernen — frühere Angebote/Rechnungen behalten ihre Kopien."""
    entry = await db.get(Customer, customer_id)
    if entry is None:
        raise HTTPException(404, "Kunde nicht gefunden.")
    await db.delete(entry)
    await db.commit()
    return {"message": f"Kunde „{entry.name}“ gelöscht"}
