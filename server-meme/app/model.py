from datetime import datetime
from typing import List
from pydantic import BaseModel
from typing import Optional

class User(BaseModel):
    username: str
    password: str
    session_id: Optional[str] = None  


