from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Customer, CustomerContact
from .utils import normalize_customer_name


def find_or_create_customer(
    session: Session,
    organization: str | None,
    email: str | None = None,
    phone: str | None = None,
    contact_name: str | None = None,
) -> Customer | None:
    if email:
        contact = session.scalar(
            select(CustomerContact).where(
                CustomerContact.kind == "email",
                CustomerContact.value == email.lower(),
            )
        )
        if contact:
            return contact.customer

    normalized = normalize_customer_name(organization)
    customer = None
    if normalized:
        customer = session.scalar(
            select(Customer).where(Customer.normalized_name == normalized)
        )

    if customer is None and organization:
        customer = Customer(
            display_name=organization.strip(),
            normalized_name=normalized or organization.strip().lower(),
        )
        session.add(customer)
        session.flush()

    if customer is None:
        return None

    for kind, value in (("email", email), ("phone", phone)):
        if not value:
            continue
        normalized_value = value.lower() if kind == "email" else value
        existing = session.scalar(
            select(CustomerContact).where(
                CustomerContact.kind == kind,
                CustomerContact.value == normalized_value,
            )
        )
        if not existing:
            session.add(
                CustomerContact(
                    customer_id=customer.id,
                    kind=kind,
                    value=normalized_value,
                    name=contact_name,
                )
            )
    session.flush()
    return customer
