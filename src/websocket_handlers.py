import json
import asyncio
import bcrypt
from datetime import datetime
from typing import Dict, Set
from sqlalchemy.orm import Session as DBSession
from src.models import (
    User, Friendship, Session, SessionParticipant, 
    SessionInvitation, ChatMessage, Achievement, UserAchievement,
    UserStatus, SessionStatus, InvitationStatus, SessionLocal
)

def create_response(message_type: str, data: dict, request_id: str = None) -> dict:
    response = {
        "type": message_type,
        "data": data
    }
    if request_id:
        response["request_id"] = request_id
    return response


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, any] = {}
        self.user_sessions: Dict[int, int] = {}
        self.session_timers: Dict[int, asyncio.Task] = {}
    
    async def connect(self, websocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        await self.set_user_online(user_id)
    
    async def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        await self.set_user_offline(user_id)
    
    async def set_user_online(self, user_id: int):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.status = UserStatus.ONLINE
                user.last_seen = datetime.utcnow()
                db.commit()
                await self.notify_friends_status_change(user_id, "online", db)
        finally:
            db.close()
    
    async def set_user_offline(self, user_id: int):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                user.status = UserStatus.OFFLINE
                user.last_seen = datetime.utcnow()
                db.commit()
                await self.notify_friends_status_change(user_id, "offline", db)
        finally:
            db.close()
    
    async def send_personal_message(self, user_id: int, message: dict):
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            try:
                await websocket.send_text(json.dumps(message))
            except Exception:
                pass
    
    async def broadcast_to_session(self, session_id: int, message: dict):
        db = SessionLocal()
        try:
            participants = db.query(SessionParticipant).filter(
                SessionParticipant.session_id == session_id
            ).all()
            for participant in participants:
                await self.send_personal_message(participant.user_id, message)
        finally:
            db.close()
    
    async def notify_friends_status_change(self, user_id: int, status: str, db: DBSession):
        friendships = db.query(Friendship).filter(
            ((Friendship.user_id == user_id) | (Friendship.friend_id == user_id)),
            Friendship.is_accepted == True
        ).all()
        
        user = db.query(User).filter(User.id == user_id).first()
        
        for friendship in friendships:
            friend_id = friendship.friend_id if friendship.user_id == user_id else friendship.user_id
            await self.send_personal_message(friend_id, {
                "type": "friend_status_changed",
                "data": {
                    "user_id": user_id,
                    "username": user.username if user else "",
                    "status": status
                }
            })


manager = ConnectionManager()


async def handle_register(data: dict, db: DBSession) -> dict:
    username = data.get("username", "").strip()
    password = data.get("password", "")
    
    if not username or len(username) < 3 or len(username) > 50:
        return {"type": "error", "message": "Username должен быть от 3 до 50 символов"}
    
    if not password or len(password) < 6:
        return {"type": "error", "message": "Пароль должен быть минимум 6 символов"}
    
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        return {"type": "error", "message": "Пользователь с таким именем уже существует"}
    
    password_hash = hash_password(password)
    user = User(username=username, password_hash=password_hash, status=UserStatus.ONLINE)
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return {
        "type": "register_success",
        "data": {
            "user_id": user.id,
            "username": user.username,
            "status": user.status.value
        }
    }


async def handle_login(data: dict, db: DBSession) -> dict:
    username = data.get("username", "").strip()
    password = data.get("password", "")
    
    if not username:
        return {"type": "error", "message": "Username обязателен"}
    
    if not password:
        return {"type": "error", "message": "Пароль обязателен"}
    
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return {"type": "error", "message": "Неверное имя пользователя или пароль"}
    
    if not verify_password(password, user.password_hash):
        return {"type": "error", "message": "Неверное имя пользователя или пароль"}
    
    user.status = UserStatus.ONLINE
    user.last_seen = datetime.utcnow()
    db.commit()
    
    return {
        "type": "login_success",
        "data": {
            "user_id": user.id,
            "username": user.username,
            "status": user.status.value,
            "total_sessions": user.total_sessions,
            "total_time_seconds": user.total_time_seconds
        }
    }


async def handle_set_status(user_id: int, data: dict, db: DBSession) -> dict:
    status_str = data.get("status", "").lower()
    try:
        new_status = UserStatus(status_str)
    except ValueError:
        return {"type": "error", "message": "Недопустимый статус"}
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"type": "error", "message": "Пользователь не найден"}
    
    user.status = new_status
    user.last_seen = datetime.utcnow()
    db.commit()
    
    await manager.notify_friends_status_change(user_id, new_status.value, db)
    
    return {
        "type": "status_changed",
        "data": {
            "status": new_status.value
        }
    }


async def handle_search_users(user_id: int, data: dict, db: DBSession) -> dict:
    query = data.get("query", "").strip()
    if len(query) < 2:
        return {"type": "error", "message": "Запрос должен содержать минимум 2 символа"}
    
    users = db.query(User).filter(
        User.username.ilike(f"%{query}%"),
        User.id != user_id
    ).limit(20).all()
    
    results = []
    for user in users:
        friendship = db.query(Friendship).filter(
            ((Friendship.user_id == user_id) & (Friendship.friend_id == user.id)) |
            ((Friendship.user_id == user.id) & (Friendship.friend_id == user_id))
        ).first()
        
        friend_status = "none"
        if friendship:
            if friendship.is_accepted:
                friend_status = "friend"
            elif friendship.user_id == user_id:
                friend_status = "request_sent"
            else:
                friend_status = "request_received"
        
        results.append({
            "user_id": user.id,
            "username": user.username,
            "status": user.status.value,
            "friendship_status": friend_status
        })
    
    return {
        "type": "search_results",
        "data": results
    }


async def handle_send_friend_request(user_id: int, data: dict, db: DBSession) -> dict:
    friend_id = data.get("friend_id")
    if not friend_id or friend_id == user_id:
        return {"type": "error", "message": "Недопустимый ID друга"}
    
    friend = db.query(User).filter(User.id == friend_id).first()
    if not friend:
        return {"type": "error", "message": "Пользователь не найден"}
    
    existing = db.query(Friendship).filter(
        ((Friendship.user_id == user_id) & (Friendship.friend_id == friend_id)) |
        ((Friendship.user_id == friend_id) & (Friendship.friend_id == user_id))
    ).first()
    
    if existing:
        if existing.is_accepted:
            return {"type": "error", "message": "Вы уже друзья"}
        else:
            return {"type": "error", "message": "Запрос уже отправлен"}
    
    friendship = Friendship(user_id=user_id, friend_id=friend_id)
    db.add(friendship)
    db.commit()
    
    sender = db.query(User).filter(User.id == user_id).first()
    await manager.send_personal_message(friend_id, {
        "type": "friend_request_received",
        "data": {
            "request_id": friendship.id,
            "from_user_id": user_id,
            "from_username": sender.username if sender else ""
        }
    })
    
    return {
        "type": "friend_request_sent",
        "data": {
            "friend_id": friend_id,
            "friend_username": friend.username
        }
    }


async def handle_respond_friend_request(user_id: int, data: dict, db: DBSession) -> dict:
    request_id = data.get("request_id")
    accept = data.get("accept", False)
    
    friendship = db.query(Friendship).filter(
        Friendship.id == request_id,
        Friendship.friend_id == user_id,
        Friendship.is_accepted == False
    ).first()
    
    if not friendship:
        return {"type": "error", "message": "Запрос не найден"}
    
    if accept:
        friendship.is_accepted = True
        friendship.accepted_at = datetime.utcnow()
        db.commit()
        
        await check_friends_achievement(user_id, db)
        await check_friends_achievement(friendship.user_id, db)
        
        user = db.query(User).filter(User.id == user_id).first()
        await manager.send_personal_message(friendship.user_id, {
            "type": "friend_request_accepted",
            "data": {
                "user_id": user_id,
                "username": user.username if user else ""
            }
        })
        
        return {
            "type": "friend_added",
            "data": {
                "friend_id": friendship.user_id,
                "friend_username": friendship.user.username
            }
        }
    else:
        db.delete(friendship)
        db.commit()
        
        return {
            "type": "friend_request_declined",
            "data": {"request_id": request_id}
        }


async def handle_get_friends(user_id: int, db: DBSession) -> dict:
    friendships = db.query(Friendship).filter(
        ((Friendship.user_id == user_id) | (Friendship.friend_id == user_id)),
        Friendship.is_accepted == True
    ).all()
    
    friends = []
    for f in friendships:
        friend_id = f.friend_id if f.user_id == user_id else f.user_id
        friend = db.query(User).filter(User.id == friend_id).first()
        if friend:
            friends.append({
                "user_id": friend.id,
                "username": friend.username,
                "status": friend.status.value,
                "last_seen": friend.last_seen.isoformat() if friend.last_seen else None
            })
    
    return {
        "type": "friends_list",
        "data": friends
    }


async def handle_get_friend_requests(user_id: int, db: DBSession) -> dict:
    requests = db.query(Friendship).filter(
        Friendship.friend_id == user_id,
        Friendship.is_accepted == False
    ).all()
    
    result = []
    for r in requests:
        sender = db.query(User).filter(User.id == r.user_id).first()
        if sender:
            result.append({
                "request_id": r.id,
                "from_user_id": sender.id,
                "from_username": sender.username,
                "created_at": r.created_at.isoformat() if r.created_at else None
            })
    
    return {
        "type": "friend_requests",
        "data": result
    }


async def handle_create_session(user_id: int, data: dict, db: DBSession) -> dict:
    duration = data.get("duration_seconds", 1800)
    if duration < 60 or duration > 7200:
        return {"type": "error", "message": "Длительность должна быть от 1 до 120 минут"}
    
    session = Session(
        creator_id=user_id,
        duration_seconds=duration,
        status=SessionStatus.PENDING
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    
    participant = SessionParticipant(session_id=session.id, user_id=user_id)
    db.add(participant)
    db.commit()
    
    return {
        "type": "session_created",
        "data": {
            "session_id": session.id,
            "duration_seconds": session.duration_seconds
        }
    }


async def handle_invite_to_session(user_id: int, data: dict, db: DBSession) -> dict:
    session_id = data.get("session_id")
    invitee_id = data.get("user_id")
    
    session = db.query(Session).filter(
        Session.id == session_id,
        Session.creator_id == user_id,
        Session.status == SessionStatus.PENDING
    ).first()
    
    if not session:
        return {"type": "error", "message": "Сессия не найдена или уже начата"}
    
    invitee = db.query(User).filter(User.id == invitee_id).first()
    if not invitee:
        return {"type": "error", "message": "Пользователь не найден"}
    
    if invitee.status != UserStatus.ONLINE:
        return {"type": "error", "message": "Пользователь не онлайн"}
    
    existing = db.query(SessionInvitation).filter(
        SessionInvitation.session_id == session_id,
        SessionInvitation.receiver_id == invitee_id,
        SessionInvitation.status == InvitationStatus.PENDING
    ).first()
    
    if existing:
        return {"type": "error", "message": "Приглашение уже отправлено"}
    
    invitation = SessionInvitation(
        session_id=session_id,
        sender_id=user_id,
        receiver_id=invitee_id
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    
    sender = db.query(User).filter(User.id == user_id).first()
    await manager.send_personal_message(invitee_id, {
        "type": "session_invitation",
        "data": {
            "invitation_id": invitation.id,
            "session_id": session_id,
            "from_user_id": user_id,
            "from_username": sender.username if sender else "",
            "duration_seconds": session.duration_seconds
        }
    })
    
    return {
        "type": "invitation_sent",
        "data": {
            "invitation_id": invitation.id,
            "to_user_id": invitee_id
        }
    }


async def handle_respond_invitation(user_id: int, data: dict, db: DBSession) -> dict:
    invitation_id = data.get("invitation_id")
    accept = data.get("accept", False)
    
    invitation = db.query(SessionInvitation).filter(
        SessionInvitation.id == invitation_id,
        SessionInvitation.receiver_id == user_id,
        SessionInvitation.status == InvitationStatus.PENDING
    ).first()
    
    if not invitation:
        return {"type": "error", "message": "Приглашение не найдено"}
    
    session = db.query(Session).filter(Session.id == invitation.session_id).first()
    if not session or session.status not in [SessionStatus.PENDING, SessionStatus.ACTIVE]:
        return {"type": "error", "message": "Сессия больше недоступна"}
    
    invitation.status = InvitationStatus.ACCEPTED if accept else InvitationStatus.DECLINED
    invitation.responded_at = datetime.utcnow()
    db.commit()
    
    if accept:
        participant = SessionParticipant(session_id=session.id, user_id=user_id)
        db.add(participant)
        db.commit()
        
        user = db.query(User).filter(User.id == user_id).first()
        await manager.send_personal_message(invitation.sender_id, {
            "type": "invitation_accepted",
            "data": {
                "session_id": session.id,
                "user_id": user_id,
                "username": user.username if user else ""
            }
        })
        
        return {
            "type": "joined_session",
            "data": {
                "session_id": session.id,
                "duration_seconds": session.duration_seconds
            }
        }
    else:
        await manager.send_personal_message(invitation.sender_id, {
            "type": "invitation_declined",
            "data": {
                "session_id": session.id,
                "user_id": user_id
            }
        })
        
        return {
            "type": "invitation_declined_success",
            "data": {"invitation_id": invitation_id}
        }


async def handle_start_session(user_id: int, data: dict, db: DBSession) -> dict:
    session_id = data.get("session_id")
    
    session = db.query(Session).filter(
        Session.id == session_id,
        Session.creator_id == user_id,
        Session.status == SessionStatus.PENDING
    ).first()
    
    if not session:
        return {"type": "error", "message": "Сессия не найдена"}
    
    participants = db.query(SessionParticipant).filter(
        SessionParticipant.session_id == session_id
    ).count()
    
    if participants < 2:
        return {"type": "error", "message": "Нужен минимум 2 участника для старта"}
    
    session.status = SessionStatus.ACTIVE
    session.started_at = datetime.utcnow()
    session.elapsed_seconds = 0
    db.commit()
    
    await manager.broadcast_to_session(session_id, {
        "type": "session_started",
        "data": {
            "session_id": session_id,
            "duration_seconds": session.duration_seconds,
            "started_at": session.started_at.isoformat()
        }
    })
    
    asyncio.create_task(run_session_timer(session_id, session.duration_seconds))
    
    return {
        "type": "session_started_success",
        "data": {
            "session_id": session_id
        }
    }


async def run_session_timer(session_id: int, duration: int):
    elapsed = 0
    while elapsed < duration:
        await asyncio.sleep(1)
        elapsed += 1
        
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if not session or session.status != SessionStatus.ACTIVE:
                break
            
            session.elapsed_seconds = elapsed
            db.commit()
            
            if elapsed % 5 == 0:
                await manager.broadcast_to_session(session_id, {
                    "type": "timer_update",
                    "data": {
                        "session_id": session_id,
                        "elapsed_seconds": elapsed,
                        "remaining_seconds": duration - elapsed
                    }
                })
        finally:
            db.close()
    
    await complete_session(session_id)


async def complete_session(session_id: int):
    db = SessionLocal()
    try:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session or session.status != SessionStatus.ACTIVE:
            return
        
        session.status = SessionStatus.COMPLETED
        session.completed_at = datetime.utcnow()
        db.commit()
        
        participants = db.query(SessionParticipant).filter(
            SessionParticipant.session_id == session_id
        ).all()
        
        for p in participants:
            user = db.query(User).filter(User.id == p.user_id).first()
            if user:
                user.total_sessions += 1
                user.total_time_seconds += session.elapsed_seconds
                db.commit()
                
                await check_session_achievements(user.id, db)
                await check_time_achievements(user.id, db)
        
        await manager.broadcast_to_session(session_id, {
            "type": "session_completed",
            "data": {
                "session_id": session_id,
                "duration_seconds": session.elapsed_seconds
            }
        })
    finally:
        db.close()


async def handle_send_chat_message(user_id: int, data: dict, db: DBSession) -> dict:
    session_id = data.get("session_id")
    content = data.get("content", "").strip()
    
    if not content or len(content) > 1000:
        return {"type": "error", "message": "Сообщение должно быть от 1 до 1000 символов"}
    
    participant = db.query(SessionParticipant).filter(
        SessionParticipant.session_id == session_id,
        SessionParticipant.user_id == user_id
    ).first()
    
    if not participant:
        return {"type": "error", "message": "Вы не участник этой сессии"}
    
    session = db.query(Session).filter(
        Session.id == session_id,
        Session.status == SessionStatus.ACTIVE
    ).first()
    
    if not session:
        return {"type": "error", "message": "Сессия не активна"}
    
    message = ChatMessage(
        session_id=session_id,
        user_id=user_id,
        content=content
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    
    user = db.query(User).filter(User.id == user_id).first()
    
    await manager.broadcast_to_session(session_id, {
        "type": "chat_message",
        "data": {
            "message_id": message.id,
            "session_id": session_id,
            "user_id": user_id,
            "username": user.username if user else "",
            "content": content,
            "created_at": message.created_at.isoformat()
        }
    })
    
    return {
        "type": "message_sent",
        "data": {"message_id": message.id}
    }


async def handle_get_achievements(user_id: int, db: DBSession) -> dict:
    user_achievements = db.query(UserAchievement).filter(
        UserAchievement.user_id == user_id
    ).all()
    
    earned_ids = {ua.achievement_id for ua in user_achievements}
    
    all_achievements = db.query(Achievement).all()
    
    result = []
    for a in all_achievements:
        result.append({
            "id": a.id,
            "key": a.key,
            "name": a.name,
            "description": a.description,
            "earned": a.id in earned_ids,
            "earned_at": next(
                (ua.earned_at.isoformat() for ua in user_achievements if ua.achievement_id == a.id),
                None
            )
        })
    
    return {
        "type": "achievements",
        "data": result
    }


async def handle_get_profile(user_id: int, db: DBSession) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"type": "error", "message": "Пользователь не найден"}
    
    achievements_count = db.query(UserAchievement).filter(
        UserAchievement.user_id == user_id
    ).count()
    
    friends_count = db.query(Friendship).filter(
        ((Friendship.user_id == user_id) | (Friendship.friend_id == user_id)),
        Friendship.is_accepted == True
    ).count()
    
    return {
        "type": "profile",
        "data": {
            "user_id": user.id,
            "username": user.username,
            "status": user.status.value,
            "total_sessions": user.total_sessions,
            "total_time_seconds": user.total_time_seconds,
            "achievements_count": achievements_count,
            "friends_count": friends_count,
            "created_at": user.created_at.isoformat() if user.created_at else None
        }
    }


async def check_session_achievements(user_id: int, db: DBSession):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return
    
    thresholds = [
        ("first_session", 1),
        ("sessions_5", 5),
        ("sessions_10", 10),
        ("sessions_25", 25),
        ("sessions_50", 50)
    ]
    
    for key, threshold in thresholds:
        if user.total_sessions >= threshold:
            await grant_achievement(user_id, key, db)


async def check_time_achievements(user_id: int, db: DBSession):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return
    
    thresholds = [
        ("total_time_1h", 3600),
        ("total_time_5h", 18000)
    ]
    
    for key, threshold in thresholds:
        if user.total_time_seconds >= threshold:
            await grant_achievement(user_id, key, db)


async def check_friends_achievement(user_id: int, db: DBSession):
    friends_count = db.query(Friendship).filter(
        ((Friendship.user_id == user_id) | (Friendship.friend_id == user_id)),
        Friendship.is_accepted == True
    ).count()
    
    if friends_count >= 5:
        await grant_achievement(user_id, "friends_5", db)


async def grant_achievement(user_id: int, achievement_key: str, db: DBSession):
    achievement = db.query(Achievement).filter(Achievement.key == achievement_key).first()
    if not achievement:
        return
    
    existing = db.query(UserAchievement).filter(
        UserAchievement.user_id == user_id,
        UserAchievement.achievement_id == achievement.id
    ).first()
    
    if existing:
        return
    
    user_achievement = UserAchievement(
        user_id=user_id,
        achievement_id=achievement.id
    )
    db.add(user_achievement)
    db.commit()
    
    await manager.send_personal_message(user_id, {
        "type": "achievement_earned",
        "data": {
            "key": achievement.key,
            "name": achievement.name,
            "description": achievement.description
        }
    })
