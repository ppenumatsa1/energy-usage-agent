from pydantic import BaseModel


class Me(BaseModel):
    """Onboarding status for the caller. Exposes only a display name, never a customer ID."""

    onboarded: bool
    customer_name: str | None = None
    timezone: str | None = None
