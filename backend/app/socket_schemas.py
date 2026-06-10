from typing import Optional
from pydantic import BaseModel, Field


class ConnectAuth(BaseModel):
    token: str


class JoinRoomData(BaseModel):
    target_id: Optional[int] = None
    group_id: Optional[int] = None
    channel_id: Optional[int] = None


class SendMessageData(BaseModel):
    receiver_id: int
    encrypted_content: str
    attachment_ids: list[int] = Field(default_factory=list)


class TypingData(BaseModel):
    receiver_id: int
    is_typing: bool


class ShareKeyData(BaseModel):
    target_id: int
    encrypted_broadcast_key: str


class PermissionRequestedData(BaseModel):
    owner_id: int


class PermissionRespondedData(BaseModel):
    requester_id: int
    status: str  # "approved" | "rejected"


class GetUserStatusData(BaseModel):
    user_id: int


class ShareGroupKeyData(BaseModel):
    group_id: int
    target_id: int
    encrypted_broadcast_key: str