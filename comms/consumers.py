import json
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
import redis.asyncio as redis

# Redis key TTL for active call (1 hour) so stale calls don't persist forever
ACTIVE_CALL_TTL = 3600


def get_redis():
    """Lazy Redis connection using same host as CHANNEL_LAYERS."""
    config = settings.CHANNEL_LAYERS["default"].get("CONFIG", {})
    hosts = config.get("hosts", [("127.0.0.1", 6379)])
    host, port = hosts[0] if isinstance(hosts[0], (list, tuple)) else ("127.0.0.1", 6379)
    return redis.from_url(f"redis://{host}:{port}", decode_responses=True)


class CallConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_authenticated:
            self.user_group = f"user_{self.user.id}"
            await self.channel_layer.group_add(
                self.user_group,
                self.channel_name
            )
            await self.accept()
            # If user was in an active call, tell client so it can re-establish
            await self._send_call_restore_if_any()
        else:
            await self.close()

    async def _send_call_restore_if_any(self):
        r = get_redis()
        key = f"active_call:{self.user.id}"
        try:
            raw = await r.get(key)
            if raw:
                data = json.loads(raw)
                await self.send(text_data=json.dumps({
                    "type": "call_restore",
                    "peer_id": data["peer_id"],
                    "role": data["role"],
                    "caller_name": data.get("caller_name", ""),
                }))
        except (json.JSONDecodeError, KeyError):
            pass
        finally:
            await r.aclose()

    async def disconnect(self, close_code):
        if hasattr(self, 'user_group'):
            await self.channel_layer.group_discard(
                self.user_group,
                self.channel_name
            )
        # Don't clear active_call on disconnect so reload can restore

    async def receive(self, text_data):
        data = json.loads(text_data)
        target_user_id = data.get("target_id")
        message_type = data.get("type")

        if message_type == "hangup" and target_user_id:
            await self._handle_hangup(target_user_id)
            return

        if target_user_id:
            if message_type == "offer":
                await self._store_active_call(target_user_id, "caller", data.get("caller_name", ""))
            target_group = f"user_{target_user_id}"
            await self.channel_layer.group_send(
                target_group,
                {
                    "type": "signaling_message",
                    "data": data,
                    "sender_id": self.user.id
                }
            )

    async def _store_active_call(self, peer_id, role, caller_name):
        """Store active call in Redis for both users so reload can restore."""
        r = get_redis()
        try:
            my_key = f"active_call:{self.user.id}"
            peer_key = f"active_call:{peer_id}"
            await r.setex(my_key, ACTIVE_CALL_TTL, json.dumps({
                "peer_id": peer_id, "role": role, "caller_name": caller_name
            }))
            other_role = "callee" if role == "caller" else "caller"
            await r.setex(peer_key, ACTIVE_CALL_TTL, json.dumps({
                "peer_id": self.user.id, "role": other_role, "caller_name": caller_name
            }))
        finally:
            await r.aclose()

    async def _handle_hangup(self, peer_id):
        """Clear active call from Redis and notify peer that call ended."""
        r = get_redis()
        try:
            await r.delete(f"active_call:{self.user.id}")
            await r.delete(f"active_call:{peer_id}")
        finally:
            await r.aclose()
        target_group = f"user_{peer_id}"
        await self.channel_layer.group_send(
            target_group,
            {
                "type": "signaling_message",
                "data": {"type": "call_ended", "sender_id": self.user.id},
                "sender_id": self.user.id,
            }
        )

    async def signaling_message(self, event):
        await self.send(text_data=json.dumps(event))
