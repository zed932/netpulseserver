
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
import enum

# Получаем DATABASE_URL из переменных окружения
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://netpulse:password@localhost:5432/netpulse"  # Значение по умолчанию
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ... остальной код без изменений


class UserStatus(enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    AWAY = "away"


class SessionStatus(enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InvitationStatus(enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    status = Column(SQLEnum(UserStatus), default=UserStatus.OFFLINE)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    total_sessions = Column(Integer, default=0)
    total_time_seconds = Column(Integer, default=0)
    
    sent_friend_requests = relationship("Friendship", foreign_keys="Friendship.user_id", back_populates="user")
    received_friend_requests = relationship("Friendship", foreign_keys="Friendship.friend_id", back_populates="friend")
    achievements = relationship("UserAchievement", back_populates="user")
    sent_invitations = relationship("SessionInvitation", foreign_keys="SessionInvitation.sender_id", back_populates="sender")
    received_invitations = relationship("SessionInvitation", foreign_keys="SessionInvitation.receiver_id", back_populates="receiver")


class Friendship(Base):
    __tablename__ = "friendships"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    friend_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_accepted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    accepted_at = Column(DateTime, nullable=True)
    
    user = relationship("User", foreign_keys=[user_id], back_populates="sent_friend_requests")
    friend = relationship("User", foreign_keys=[friend_id], back_populates="received_friend_requests")


class Session(Base):
    __tablename__ = "sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(SQLEnum(SessionStatus), default=SessionStatus.PENDING)
    duration_seconds = Column(Integer, default=1800)
    elapsed_seconds = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    creator = relationship("User", foreign_keys=[creator_id])
    participants = relationship("SessionParticipant", back_populates="session")
    messages = relationship("ChatMessage", back_populates="session")


class SessionParticipant(Base):
    __tablename__ = "session_participants"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow)
    
    session = relationship("Session", back_populates="participants")
    user = relationship("User")


class SessionInvitation(Base):
    __tablename__ = "session_invitations"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(SQLEnum(InvitationStatus), default=InvitationStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    responded_at = Column(DateTime, nullable=True)
    
    session = relationship("Session")
    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_invitations")
    receiver = relationship("User", foreign_keys=[receiver_id], back_populates="received_invitations")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    session = relationship("Session", back_populates="messages")
    user = relationship("User")


class Achievement(Base):
    __tablename__ = "achievements"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    threshold = Column(Integer, default=1)


class UserAchievement(Base):
    __tablename__ = "user_achievements"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    achievement_id = Column(Integer, ForeignKey("achievements.id"), nullable=False)
    earned_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="achievements")
    achievement = relationship("Achievement")


def init_db():
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        from src.config import ACHIEVEMENT_TYPES
        for key, data in ACHIEVEMENT_TYPES.items():
            existing = db.query(Achievement).filter(Achievement.key == key).first()
            if not existing:
                achievement = Achievement(
                    key=key,
                    name=data["name"],
                    description=data["description"],
                    threshold=data["threshold"]
                )
                db.add(achievement)
        db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
