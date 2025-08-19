from pydantic import BaseModel

class RelayState(BaseModel):
    relay: int
    on: bool
