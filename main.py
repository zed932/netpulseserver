import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from src.models import init_db, SessionLocal
from src.rest_api import router as api_router
from src.websocket_handlers import (
    manager,
    handle_register,
    handle_login,
    handle_set_status,
    handle_search_users,
    handle_send_friend_request,
    handle_respond_friend_request,
    handle_get_friends,
    handle_get_friend_requests,
    handle_create_session,
    handle_invite_to_session,
    handle_respond_invitation,
    handle_start_session,
    handle_send_chat_message,
    handle_get_achievements,
    handle_get_profile
)
from src.config import HOST, PORT


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("Database initialized")
    yield
    print("Shutting down...")


app = FastAPI(
    title="NetPulse API",
    description="WebSocket and REST API server for NetPulse iOS application",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "service": "NetPulse Server",
        "version": "1.0.0",
        "websocket_endpoint": "/ws",
        "api_docs": "/docs",
        "health": "/api/health"
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    user_id = None

    try:
        await websocket.accept()

        while True:
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "data": {"message": "Invalid JSON format"},
                    "request_id": message.get("request_id")
                }))
                continue

            msg_type = message.get("type", "")
            msg_data = message.get("data", {})
            request_id = message.get("request_id")

            db = SessionLocal()
            try:
                response = None

                if msg_type == "register":
                    response = await handle_register(msg_data, db)
                elif msg_type == "login":
                    response = await handle_login(msg_data, db)
                    if response.get("type") == "login_success":
                        user_id = response["data"]["user_id"]
                        manager.active_connections[user_id] = websocket
                        await manager.set_user_online(user_id)
                elif msg_type == "set_status":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_set_status(user_id, msg_data, db)
                elif msg_type == "search_users":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_search_users(user_id, msg_data, db)
                elif msg_type == "send_friend_request":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_send_friend_request(user_id, msg_data, db)
                elif msg_type == "respond_friend_request":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_respond_friend_request(user_id, msg_data, db)
                elif msg_type == "get_friends":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_get_friends(user_id, db)
                elif msg_type == "get_friend_requests":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_get_friend_requests(user_id, db)
                elif msg_type == "create_session":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_create_session(user_id, msg_data, db)
                elif msg_type == "invite_to_session":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_invite_to_session(user_id, msg_data, db)
                elif msg_type == "respond_invitation":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_respond_invitation(user_id, msg_data, db)
                elif msg_type == "start_session":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_start_session(user_id, msg_data, db)
                elif msg_type == "send_message":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_send_chat_message(user_id, msg_data, db)
                elif msg_type == "get_achievements":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_get_achievements(user_id, db)
                elif msg_type == "get_profile":
                    if not user_id:
                        response = {"type": "error", "data": {"message": "Not authenticated"}}
                    else:
                        response = await handle_get_profile(user_id, db)
                elif msg_type == "ping":
                    response = {"type": "pong", "data": {}}
                else:
                    response = {"type": "error", "data": {"message": f"Unknown message type: {msg_type}"}}

                # Добавляем request_id к ответу
                if request_id and isinstance(response, dict):
                    response["request_id"] = request_id

                await websocket.send_text(json.dumps(response))

            finally:
                db.close()

    except WebSocketDisconnect:
        if user_id:
            await manager.disconnect(user_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if user_id:
            await manager.disconnect(user_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)