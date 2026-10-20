"""The result of an action, as shown to the user (R17.4, R18.1)."""

from typing import Literal

from pydantic import BaseModel


class ActionResult(BaseModel):
    """What an action ended in, with its French message."""

    level: Literal['success', 'error', 'warning']
    message: str
