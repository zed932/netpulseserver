# Исправленный server.py
from fastapi import FastAPI, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import json
import asyncio
from typing import Dict, List, Optional
import time
from datetime import datetime
import uuid

app = FastAPI(title="NetPulse API", version="0.0.3")

# Настройки CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В разработке разрешаем все источники
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Модели данных
class UserCreate(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UpdateStatusRequest(BaseModel):
    status: str


# "База данных" в памяти с исправленными форматами дат
def get_current_iso_date():
    return datetime.now().isoformat() + "Z"


users_db = [
    {
        "id": 1,
        "username": "test",
        "password": "test123",
        "status": "online",
        "total_sessions": 5,
        "total_time_seconds": 3600,
        "created_at": get_current_iso_date(),
        "last_seen": get_current_iso_date()
    },
    {
        "id": 2,
        "username": "alice",
        "password": "alice123",
        "status": "away",
        "total_sessions": 3,
        "total_time_seconds": 1800,
        "created_at": get_current_iso_date(),
        "last_seen": get_current_iso_date()
    },
    {
        "id": 3,
        "username": "bob",
        "password": "bob123",
        "status": "busy",
        "total_sessions": 8,
        "total_time_seconds": 7200,
        "created_at": get_current_iso_date(),
        "last_seen": get_current_iso_date()
    }
]

friends_db = {
    1: [2, 3],  # test дружит с alice и bob
    2: [1, 3],  # alice дружит с test и bob
    3: [1, 2]  # bob дружит с test и alice
}

# WebSocket connections
websocket_connections: List[WebSocket] = []


# REST API endpoints
@app.get("/")
async def root():
    return {"message": "NetPulse API Server", "status": "running", "version": "0.0.3"}


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": time.time(), "users_count": len(users_db)}


@app.post("/api/register")
async def register_user(request: UserCreate):
    # Проверяем, существует ли пользователь
    for user in users_db:
        if user["username"] == request.username:
            raise HTTPException(status_code=400, detail="User already exists")

    # Создаем нового пользователя
    new_user = {
        "id": len(users_db) + 1,
        "username": request.username,
        "password": request.password,
        "status": "online",
        "total_sessions": 0,
        "total_time_seconds": 0,
        "created_at": get_current_iso_date(),
        "last_seen": get_current_iso_date()
    }
    users_db.append(new_user)

    # Создаем пустой список друзей
    friends_db[new_user["id"]] = []

    return {
        "success": True,
        "user": {
            "user_id": new_user["id"],
            "username": new_user["username"],
            "status": new_user["status"],
            "total_sessions": new_user["total_sessions"],
            "total_time_seconds": new_user["total_time_seconds"],
            "created_at": new_user["created_at"],
            "last_seen": new_user["last_seen"]
        }
    }


@app.post("/api/login")
async def login_user(request: LoginRequest):
    for user in users_db:
        if user["username"] == request.username and user["password"] == request.password:
            # Обновляем last_seen
            user["last_seen"] = get_current_iso_date()
            user["status"] = "online"  # При логине ставим статус "online"

            return {
                "success": True,
                "user": {
                    "user_id": user["id"],
                    "id": user["id"],  # Добавляем оба ключа для совместимости
                    "username": user["username"],
                    "status": user["status"],
                    "total_sessions": user["total_sessions"],
                    "total_time_seconds": user["total_time_seconds"],
                    "created_at": user["created_at"],
                    "last_seen": user["last_seen"]
                }
            }

    raise HTTPException(status_code=401, detail="Invalid credentials")


@app.get("/api/users")
async def get_users():
    return {
        "users": [
            {
                "id": user["id"],
                "username": user["username"],
                "status": user["status"],
                "total_sessions": user["total_sessions"],
                "total_time_seconds": user["total_time_seconds"]
            }
            for user in users_db
        ]
    }


@app.get("/api/users/{user_id}")
async def get_user(user_id: int):
    user = next((u for u in users_db if u["id"] == user_id), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "status": user["status"],
            "total_sessions": user["total_sessions"],
            "total_time_seconds": user["total_time_seconds"],
            "created_at": user["created_at"],
            "last_seen": user["last_seen"]
        }
    }


@app.post("/api/users/{user_id}/status")
async def update_user_status(user_id: int, request: UpdateStatusRequest):
    user = next((u for u in users_db if u["id"] == user_id), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Валидация статуса
    valid_statuses = ["online", "offline", "busy", "away"]
    if request.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Valid statuses: {valid_statuses}")

    # Обновляем статус
    user["status"] = request.status
    user["last_seen"] = get_current_iso_date()

    # Отправляем уведомление через WebSocket
    notification = {
        "type": "friend_status_changed",
        "data": {
            "user_id": user_id,
            "username": user["username"],
            "status": request.status
        }
    }

    # Отправляем всем активным WebSocket соединениям
    await broadcast_message(json.dumps(notification))

    return {"success": True, "status": request.status}


@app.get("/api/users/{user_id}/friends")
async def get_user_friends(user_id: int):
    if user_id not in friends_db:
        return {"friends": []}

    friends_list = []
    for friend_id in friends_db[user_id]:
        friend = next((u for u in users_db if u["id"] == friend_id), None)
        if friend:
            friends_list.append({
                "id": friend["id"],
                "user_id": friend["id"],  # Добавляем user_id для совместимости
                "username": friend["username"],
                "status": friend["status"],
                "total_sessions": friend["total_sessions"],
                "total_time_seconds": friend["total_time_seconds"],
                "last_seen": friend["last_seen"]
            })

    return {"friends": friends_list}


@app.post("/api/users/{user_id}/friends/{friend_id}")
async def add_friend(user_id: int, friend_id: int):
    if user_id not in friends_db:
        friends_db[user_id] = []

    if friend_id not in friends_db[user_id]:
        friends_db[user_id].append(friend_id)

    # Также добавляем обратную связь (дружба двусторонняя)
    if friend_id not in friends_db:
        friends_db[friend_id] = []

    if user_id not in friends_db[friend_id]:
        friends_db[friend_id].append(user_id)

    return {"success": True}


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    websocket_connections.append(websocket)

    client_id = id(websocket)
    print(f"New WebSocket connection: {client_id}")

    try:
        while True:
            # Получаем сообщение
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                message_type = message.get("type")
                message_data = message.get("data", {})

                print(f"WebSocket message from {client_id}: {message_type}")

                # Обработка разных типов сообщений
                if message_type == "ping":
                    response = {
                        "type": "pong",
                        "data": {"timestamp": time.time()}
                    }
                    await websocket.send_text(json.dumps(response))

                elif message_type == "login":
                    user_id = message_data.get("user_id")

                    user = next((u for u in users_db if u["id"] == user_id), None)

                    if user:
                        success_response = {
                            "type": "login_success",
                            "data": {
                                "user_id": user["id"],
                                "username": user["username"],
                                "status": user["status"]
                            }
                        }
                        await websocket.send_text(json.dumps(success_response))

                        # Отправляем список друзей
                        friends = friends_db.get(user["id"], [])
                        friends_data = []
                        for friend_id in friends:
                            friend = next((u for u in users_db if u["id"] == friend_id), None)
                            if friend:
                                friends_data.append({
                                    "id": friend["id"],
                                    "username": friend["username"],
                                    "status": friend["status"],
                                    "last_seen": friend["last_seen"]
                                })

                        friends_response = {
                            "type": "friends_list",
                            "data": {"friends": friends_data}
                        }
                        await websocket.send_text(json.dumps(friends_response))
                    else:
                        error_response = {
                            "type": "error",
                            "data": {"message": "User not found"}
                        }
                        await websocket.send_text(json.dumps(error_response))

                elif message_type == "set_status":
                    user_id = message_data.get("user_id")
                    status = message_data.get("status")

                    user = next((u for u in users_db if u["id"] == user_id), None)
                    if user:
                        # Валидация статуса
                        valid_statuses = ["online", "offline", "busy", "away"]
                        if status not in valid_statuses:
                            await websocket.send_text(json.dumps({
                                "type": "error",
                                "data": {"message": f"Invalid status. Valid: {valid_statuses}"}
                            }))
                            continue

                        user["status"] = status
                        user["last_seen"] = get_current_iso_date()

                        response = {
                            "type": "status_updated",
                            "data": {
                                "user_id": user_id,
                                "status": status
                            }
                        }
                        await websocket.send_text(json.dumps(response))

                        # Рассылаем уведомление друзьям
                        notification = {
                            "type": "friend_status_changed",
                            "data": {
                                "user_id": user_id,
                                "username": user["username"],
                                "status": status
                            }
                        }
                        await broadcast_message(json.dumps(notification))

                else:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "data": {"message": f"Unknown message type: {message_type}"}
                    }))

            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "data": {"message": "Invalid JSON format"}
                }))

    except WebSocketDisconnect:
        print(f"Client disconnected: {client_id}")
        if websocket in websocket_connections:
            websocket_connections.remove(websocket)
    except Exception as e:
        print(f"WebSocket error for {client_id}: {e}")
        if websocket in websocket_connections:
            websocket_connections.remove(websocket)


async def broadcast_message(message: str):
    disconnected = []
    for connection in websocket_connections:
        try:
            await connection.send_text(message)
        except:
            disconnected.append(connection)

    for connection in disconnected:
        if connection in websocket_connections:
            websocket_connections.remove(connection)


if __name__ == "__main__":
    print("🚀 NetPulse Server запущен")
    print("📡 REST API: http://localhost:8000")
    print("📚 API Documentation: http://localhost:8000/docs")
    print("🔌 WebSocket: ws://localhost:8000/ws")
    print("👨‍💼 Admin Panel: http://localhost:8000/admin")
    print("\n🔑 Тестовые пользователи:")
    print("  test / test123")
    print("  alice / alice123")
    print("  bob / bob123")

    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)