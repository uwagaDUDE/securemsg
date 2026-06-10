from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, BaseUpdates


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256))
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    encrypted_private_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    broadcast_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    key_sharing_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)

    sent_messages: Mapped[list["Message"]] = relationship(
        foreign_keys="Message.sender_id", back_populates="sender"
    )
    received_messages: Mapped[list["Message"]] = relationship(
        foreign_keys="Message.receiver_id", back_populates="receiver"
    )


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("owner_id", "requester_id", name="uq_permission_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    requester_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class KeyVerification(Base):
    __tablename__ = "key_verifications"
    __table_args__ = (UniqueConstraint("user_id", "contact_id", name="uq_key_verification"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    contact_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    sas_hash: Mapped[str] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class KeyRotation(Base):
    __tablename__ = "key_rotations"
    __table_args__ = (UniqueConstraint("user_id", "epoch", name="uq_key_rotation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    epoch: Mapped[int] = mapped_column(Integer)
    broadcast_key: Mapped[bytes] = mapped_column(LargeBinary)
    previous_broadcast_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    receiver_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    channel_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("channels.id"), nullable=True)
    group_chat_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("group_chats.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(16), default="user")
    encrypted_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    sender: Mapped["User"] = relationship(foreign_keys=[sender_id], back_populates="sent_messages")
    receiver: Mapped["User"] = relationship(foreign_keys=[receiver_id], back_populates="received_messages")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="message", order_by="Attachment.id")
    reactions: Mapped[list["MessageReaction"]] = relationship(back_populates="message", order_by="MessageReaction.id")


class MessageReaction(Base):
    __tablename__ = "message_reactions"
    __table_args__ = (UniqueConstraint("message_id", "user_id", "emoji", name="uq_reaction"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey("messages.id"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    emoji: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    message: Mapped["Message"] = relationship(back_populates="reactions")


class MessageVisibility(Base):
    __tablename__ = "message_visibility"
    __table_args__ = (UniqueConstraint("user_id", "message_id", name="uq_msg_visibility"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey("messages.id"))
    hidden: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class Block(Base):
    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("blocker_id", "blocked_id", name="uq_block"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    blocker_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    blocked_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    invite_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class ChannelSubscriber(Base):
    __tablename__ = "channel_subscribers"
    __table_args__ = (UniqueConstraint("channel_id", "user_id", name="uq_channel_sub"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("channels.id"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class GroupChat(Base):
    __tablename__ = "group_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    invite_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("group_chats.id"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16), default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class GroupSharedKey(Base):
    __tablename__ = "group_shared_keys"
    __table_args__ = (UniqueConstraint("group_id", "owner_id", "target_id", name="uq_group_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("group_chats.id"))
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    target_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    encrypted_broadcast_key: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class GroupBan(Base):
    __tablename__ = "group_bans"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_ban"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("group_chats.id"))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class SharedKey(Base):
    __tablename__ = "shared_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    target_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    encrypted_broadcast_key: Mapped[bytes] = mapped_column(LargeBinary)


class KeyRequest(Base):
    __tablename__ = "key_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requester_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    target_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True)
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey("messages.id"), nullable=True)
    uploader_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary)
    mime_type: Mapped[str] = mapped_column(String(32), default="image/jpeg")
    original_size: Mapped[int] = mapped_column(Integer, default=0)
    compressed_size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    message: Mapped["Message"] = relationship(back_populates="attachments")


class RateLimitEntry(Base):
    __tablename__ = "rate_limits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(256), index=True)
    timestamp: Mapped[float] = mapped_column(Float, default=0.0)
    is_block: Mapped[bool] = mapped_column(Boolean, default=False)
    block_until: Mapped[float] = mapped_column(Float, default=0.0)


# ═══════════════════════════════════════════════════════════════════════════
# Changelog / Updates — separate database for AI assistants to write to
# ═══════════════════════════════════════════════════════════════════════════

class ChangelogEntry(BaseUpdates):
    __tablename__ = "changelog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(64), default="system")
    tags: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
