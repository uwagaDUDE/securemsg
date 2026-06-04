import base64
from datetime import datetime

from pydantic import BaseModel, Field, field_serializer, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    public_key: str | None = None
    encrypted_private_key: str | None = None
    broadcast_key: str | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError("Username must contain only letters, digits, and underscores")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


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


class ReactionOut(BaseModel):
    emoji: str
    user_id: int
    count: int = 1

    model_config = {"from_attributes": True}


class AttachmentOut(BaseModel):
    id: int
    mime_type: str
    compressed_size: int

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    sender_id: int
    receiver_id: int | None = None
    channel_id: int | None = None
    group_chat_id: int | None = None
    type: str = "user"
    encrypted_content: str | None = None
    content: str | None = None
    is_read: bool
    edited_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    sender_username: str | None = None
    attachments: list[AttachmentOut] = []
    reactions: list[ReactionOut] = []

    model_config = {"from_attributes": True}


class SharedKeyOut(BaseModel):
    owner_id: int
    encrypted_broadcast_key: bytes

    @field_serializer("encrypted_broadcast_key")
    def serialize_key(v: bytes) -> str:
        return base64.b64encode(v).decode("ascii")


class SendMessageRequest(BaseModel):
    encrypted_content: str
    attachment_ids: list[int] = []


class PermissionOut(BaseModel):
    id: int
    owner_id: int
    requester_id: int
    status: str
    owner_username: str
    requester_username: str
    created_at: datetime


class EditMessageRequest(BaseModel):
    encrypted_content: str | None = None
    content: str | None = None


class ReactionRequest(BaseModel):
    emoji: str = Field(min_length=1, max_length=8)


class BlockedUserOut(BaseModel):
    id: int
    username: str
    blocked_at: datetime


class ChannelOut(BaseModel):
    id: int
    name: str
    owner_id: int
    description: str | None = None
    is_system: bool = False
    subscriber_count: int = 0
    is_subscribed: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class ChannelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class GroupChatOut(BaseModel):
    id: int
    name: str
    owner_id: int
    invite_code: str | None = None
    member_count: int = 0
    is_member: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupChatCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class GroupMemberOut(BaseModel):
    user_id: int
    username: str
    role: str
    has_key: bool = False
    public_key: bytes | None = None

    @field_serializer("public_key")
    def serialize_pk(v: bytes | None) -> str | None:
        return base64.b64encode(v).decode("ascii") if v else None


class GroupChatInfoOut(BaseModel):
    id: int
    name: str
    owner_id: int
    member_count: int

    model_config = {"from_attributes": True}


class GroupBanOut(BaseModel):
    user_id: int
    username: str
    created_at: datetime


class ChangelogEntryOut(BaseModel):
    id: int
    version: str
    title: str
    description: str
    author: str
    tags: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
