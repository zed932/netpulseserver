import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from src.models import (
    User, Friendship, Session, SessionParticipant,
    Achievement, UserAchievement, UserStatus, SessionStatus,
    get_db
)

router = APIRouter(prefix="/api", tags=["api"])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


class UserCreate(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    status: str
    total_sessions: int
    total_time_seconds: int
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class FriendResponse(BaseModel):
    user_id: int
    username: str
    status: str
    last_seen: Optional[datetime]


class AchievementResponse(BaseModel):
    id: int
    key: str
    name: str
    description: str
    earned: bool
    earned_at: Optional[datetime]


class ProfileResponse(BaseModel):
    user_id: int
    username: str
    status: str
    total_sessions: int
    total_time_seconds: int
    achievements_count: int
    friends_count: int
    created_at: Optional[datetime]


class SessionResponse(BaseModel):
    id: int
    creator_id: int
    status: str
    duration_seconds: int
    elapsed_seconds: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


class UserLogin(BaseModel):
    username: str
    password: str


@router.post("/register", response_model=UserResponse)
def register_user(user_data: UserCreate, db: DBSession = Depends(get_db)):
    username = user_data.username.strip()
    password = user_data.password
    
    if not username or len(username) < 3 or len(username) > 50:
        raise HTTPException(status_code=400, detail="Username должен быть от 3 до 50 символов")
    
    if not password or len(password) < 6:
        raise HTTPException(status_code=400, detail="Пароль должен быть минимум 6 символов")
    
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
    
    password_hash = hash_password(password)
    user = User(username=username, password_hash=password_hash, status=UserStatus.OFFLINE)
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return UserResponse(
        id=user.id,
        username=user.username,
        status=user.status.value,
        total_sessions=user.total_sessions,
        total_time_seconds=user.total_time_seconds,
        created_at=user.created_at
    )


@router.post("/login", response_model=UserResponse)
def login_user(user_data: UserLogin, db: DBSession = Depends(get_db)):
    username = user_data.username.strip()
    password = user_data.password
    
    if not username:
        raise HTTPException(status_code=400, detail="Username обязателен")
    
    if not password:
        raise HTTPException(status_code=400, detail="Пароль обязателен")
    
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
    
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
    
    return UserResponse(
        id=user.id,
        username=user.username,
        status=user.status.value,
        total_sessions=user.total_sessions,
        total_time_seconds=user.total_time_seconds,
        created_at=user.created_at
    )


@router.get("/user/{username}", response_model=UserResponse)
def get_user_by_username(username: str, db: DBSession = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return UserResponse(
        id=user.id,
        username=user.username,
        status=user.status.value,
        total_sessions=user.total_sessions,
        total_time_seconds=user.total_time_seconds,
        created_at=user.created_at
    )


@router.get("/user/id/{user_id}", response_model=UserResponse)
def get_user_by_id(user_id: int, db: DBSession = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return UserResponse(
        id=user.id,
        username=user.username,
        status=user.status.value,
        total_sessions=user.total_sessions,
        total_time_seconds=user.total_time_seconds,
        created_at=user.created_at
    )


@router.get("/profile/{user_id}", response_model=ProfileResponse)
def get_profile(user_id: int, db: DBSession = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    achievements_count = db.query(UserAchievement).filter(
        UserAchievement.user_id == user_id
    ).count()
    
    friends_count = db.query(Friendship).filter(
        ((Friendship.user_id == user_id) | (Friendship.friend_id == user_id)),
        Friendship.is_accepted == True
    ).count()
    
    return ProfileResponse(
        user_id=user.id,
        username=user.username,
        status=user.status.value,
        total_sessions=user.total_sessions,
        total_time_seconds=user.total_time_seconds,
        achievements_count=achievements_count,
        friends_count=friends_count,
        created_at=user.created_at
    )


@router.get("/friends/{user_id}", response_model=List[FriendResponse])
def get_friends(user_id: int, db: DBSession = Depends(get_db)):
    friendships = db.query(Friendship).filter(
        ((Friendship.user_id == user_id) | (Friendship.friend_id == user_id)),
        Friendship.is_accepted == True
    ).all()
    
    friends = []
    for f in friendships:
        friend_id = f.friend_id if f.user_id == user_id else f.user_id
        friend = db.query(User).filter(User.id == friend_id).first()
        if friend:
            friends.append(FriendResponse(
                user_id=friend.id,
                username=friend.username,
                status=friend.status.value,
                last_seen=friend.last_seen
            ))
    
    return friends


@router.get("/achievements/{user_id}", response_model=List[AchievementResponse])
def get_achievements(user_id: int, db: DBSession = Depends(get_db)):
    user_achievements = db.query(UserAchievement).filter(
        UserAchievement.user_id == user_id
    ).all()
    
    earned_map = {ua.achievement_id: ua.earned_at for ua in user_achievements}
    
    all_achievements = db.query(Achievement).all()
    
    result = []
    for a in all_achievements:
        result.append(AchievementResponse(
            id=a.id,
            key=a.key,
            name=a.name,
            description=a.description,
            earned=a.id in earned_map,
            earned_at=earned_map.get(a.id)
        ))
    
    return result


@router.get("/sessions/{user_id}", response_model=List[SessionResponse])
def get_user_sessions(user_id: int, db: DBSession = Depends(get_db)):
    participations = db.query(SessionParticipant).filter(
        SessionParticipant.user_id == user_id
    ).all()
    
    session_ids = [p.session_id for p in participations]
    
    sessions = db.query(Session).filter(
        Session.id.in_(session_ids)
    ).order_by(Session.created_at.desc()).limit(50).all()
    
    result = []
    for s in sessions:
        result.append(SessionResponse(
            id=s.id,
            creator_id=s.creator_id,
            status=s.status.value,
            duration_seconds=s.duration_seconds,
            elapsed_seconds=s.elapsed_seconds,
            started_at=s.started_at,
            completed_at=s.completed_at,
            created_at=s.created_at
        ))
    
    return result


@router.get("/health")
def health_check():
    return {"status": "ok", "service": "NetPulse API"}


@router.get("/stats")
def get_stats(db: DBSession = Depends(get_db)):
    total_users = db.query(User).count()
    online_users = db.query(User).filter(User.status == UserStatus.ONLINE).count()
    total_sessions = db.query(Session).filter(Session.status == SessionStatus.COMPLETED).count()
    active_sessions = db.query(Session).filter(Session.status == SessionStatus.ACTIVE).count()
    
    return {
        "total_users": total_users,
        "online_users": online_users,
        "total_completed_sessions": total_sessions,
        "active_sessions": active_sessions
    }
