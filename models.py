from pydantic import BaseModel
from typing import Optional


class RestaurantContext(BaseModel):

    model_config = {"arbitrary_types_allowed": True}

    customer_name: str = "Guest"
    party_size: Optional[int] = None
    dietary_preferences: Optional[str] = None
    phone_number: Optional[str] = None
    reservation_confirmation_id: Optional[str] = None


class InputGuardRailOutput(BaseModel):

    is_off_topic: bool
    reason: str


class OutputGuardRailOutput(BaseModel):

    is_unprofessional: bool
    reason: str


class HandoffData(BaseModel):

    to_agent_name: str
    request_type: str
    request_description: str
    reason: str
