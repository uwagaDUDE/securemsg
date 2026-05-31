import base64
from datetime import datetime

from pydantic import BaseModel, field_serializer


class RegisterRequest(BaseModel):
    username: str
    password: str
    public_key: str | None = None
    encrypted_private_key: str | None = None
    broadcast_key: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    user_id: int
    username: str


class UserOut(BaseModel):
    id: int
    username: str
    public_key: bytes | None
    encrypted_private_key: bytes | None
    broadcast_key: bytes | None
    permission_status: str = "none"
    is_online: bool = False
    last_seen: datetime | None = None

    model_config = {"from_attributes": True}

    @field_serializer("public_key", "encrypted_private_key", "broadcast_key")
    def serialize_bytes(v: bytes | None) -> str | None:
        return base64.b64encode(v).decode("ascii") if v else None


class MessageOut(BaseModel):
    id: int
    sender_id: int
    receiver_id: int
    type: str = "user"
    encrypted_content: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SharedKeyOut(BaseModel):
    owner_id: int
    encrypted_broadcast_key: bytes

    @field_serializer("encrypted_broadcast_key")
    def serialize_key(v: bytes) -> str:
        return base64.b64encode(v).decode("ascii")


class PermissionOut(BaseModel):
    id: int
    owner_id: int
    requester_id: int
    status: str
    owner_username: str
    requester_username: str
    created_at: datetime
