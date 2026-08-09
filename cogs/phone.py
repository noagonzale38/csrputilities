"""In-game "Phone" system driven by PRC event webhooks.

Players talk to the bot with `;` chat messages (delivered to us via the PRC
Event Webhook -> /webhooks/erlc route in dashboard_web.py) and the bot answers
with `:pm` commands through POST /v2/server/command.

Commands (in-game):
    ;call {username}    start a call (target must be in the server)
    ;accept             answer an incoming call / group invite
    ;decline            reject an incoming call / group invite
    ;call end           leave the call (ends it when only 2 people remain)
    ;calladd {username} invite another player into your current call
    ;tagged             tell the last speaker their message was tagged; resend it
    ;block {username}   block a player from calling you (and you them)
    ;unblock {username} lift a block
    ;{message}          while in a call, relays the message to everyone else

Calls are groups of 2+ members. Relayed messages are sent as a single `:pm`
with comma-separated recipients, so group size doesn't multiply API calls.

The /v2/server/command route is rate limited to roughly 1 request per 5
seconds per server, so every PM goes through a single queue that sends one
command every 5 seconds.
"""

import asyncio
import json
import logging
import os
import time
import uuid

from discord.ext import commands, tasks

from config import HEADERS, KEY_HEADERS, BASE_DIR
from cogs.erlc import _resolve_roblox_users
from cogs.helpers import api_get, api_post

log = logging.getLogger(__name__)

PRC_COMMAND_URL = "https://api.erlc.gg/v2/server/command"
PRC_PLAYERS_URL = "https://api.erlc.gg/v1/server/players"
PRC_HEADERS = HEADERS

PHONE_DATA_FILE = os.path.join(str(BASE_DIR), "phone_data.json")

PM_SEND_INTERVAL = 0            # seconds between :pm commands; the documented
                                # command-route limit is ~1/5s but 429s are
                                # handled with retry_after, so bursts recover
CALL_INACTIVITY_TIMEOUT = 300   # 5 minutes with no messages ends the call
RING_TIMEOUT = 60               # seconds an unanswered ring/invite lasts
MAX_CALL_MEMBERS = 8            # cap on group call size


def _load_phone_data() -> dict:
    try:
        with open(PHONE_DATA_FILE, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        data = {}

    data.setdefault("groups", {})
    data.setdefault("members", {})
    data.setdefault("blocks", {})

    # Migrate the old pairwise format ({"calls": {user: {partner...}}}).
    old_calls = data.pop("calls", None)
    if isinstance(old_calls, dict):
        seen = set()
        for user_key, call in old_calls.items():
            partner_key = call.get("partner_key")
            pair = frozenset((user_key, partner_key))
            if not partner_key or pair in seen:
                continue
            seen.add(pair)
            call_id = uuid.uuid4().hex[:8]
            data["groups"][call_id] = {
                "members": {
                    user_key: call.get("name", user_key),
                    partner_key: call.get("partner", partner_key),
                },
                "started": call.get("started", time.time()),
                "last_activity": call.get("last_activity", time.time()),
            }
            data["members"][user_key] = call_id
            data["members"][partner_key] = call_id
    return data


class PhoneSystem(commands.Cog):
    """Player-to-player phone calls (with group calls) over in-game PMs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = _load_phone_data()
        # groups:  {call_id: {"members": {user_key: display_name}, "started": ts, "last_activity": ts}}
        # members: {user_key: call_id}
        # blocks:  {blocker_lower: [blocked_lower, ...]}
        self.pending: dict[str, dict] = {}
        # pending: target_key -> {"from": name, "from_key": str, "to": name,
        #                         "created": float, "call_id": str | None}
        # call_id is set when the ring is an invite into an existing group call.
        self.pending_out: dict[str, str] = {}  # inviter_key -> target_key
        self.pm_queue: asyncio.Queue = asyncio.Queue()
        self._pm_worker_task: asyncio.Task | None = None
        self._username_cache: dict[str, str] = {}  # roblox user id -> username

    async def cog_load(self):
        self._pm_worker_task = asyncio.create_task(self._pm_worker())
        self.call_maintenance.start()

    async def cog_unload(self):
        self.call_maintenance.cancel()
        if self._pm_worker_task:
            self._pm_worker_task.cancel()

    # ------------------------------------------------------------------ state

    def _save(self):
        try:
            with open(PHONE_DATA_FILE, "w") as f:
                json.dump(self.data, f, indent=4)
        except OSError:
            log.exception("[Phone] Failed to save phone data")

    def _group_of(self, user_key: str) -> tuple[str | None, dict | None]:
        call_id = self.data["members"].get(user_key)
        if call_id is None:
            return None, None
        group = self.data["groups"].get(call_id)
        if group is None:
            # Repair dangling membership.
            self.data["members"].pop(user_key, None)
            return None, None
        return call_id, group

    def _others(self, group: dict, exclude_key: str) -> list[str]:
        return [name for key, name in group["members"].items() if key != exclude_key]

    def _is_blocked(self, a_key: str, b_key: str) -> bool:
        """True if either player has blocked the other."""
        blocks = self.data["blocks"]
        return b_key in blocks.get(a_key, []) or a_key in blocks.get(b_key, [])

    def _is_busy(self, user_key: str) -> bool:
        return (
            user_key in self.data["members"]
            or user_key in self.pending
            or user_key in self.pending_out
        )

    def _remove_member(self, call_id: str, group: dict, user_key: str):
        group["members"].pop(user_key, None)
        self.data["members"].pop(user_key, None)
        if len(group["members"]) <= 1:
            # A call needs at least two people; dissolve it.
            for last_key in list(group["members"]):
                self.data["members"].pop(last_key, None)
            self.data["groups"].pop(call_id, None)

    # --------------------------------------------------------------- messaging

    def _queue_pm(self, recipients, message: str):
        """Queue a PM. `recipients` is one username or a list of usernames;
        a list becomes a single comma-separated :pm command."""
        if isinstance(recipients, (list, tuple, set)):
            recipients = [r for r in recipients if r]
            if not recipients:
                return
            recipients = ",".join(recipients)
        self.pm_queue.put_nowait((recipients, message))

    async def _pm_worker(self):
        """Send queued PMs one at a time, spaced to respect the command rate limit."""
        while True:
            username, message = await self.pm_queue.get()
            try:
                await self._send_command(f":pm {username} {message}")
            except Exception:
                log.exception("[Phone] Failed to send PM to %s", username)
            await asyncio.sleep(PM_SEND_INTERVAL)

    async def _send_command(self, command: str):
        for _attempt in range(2):
            status, resp = await api_post(
                PRC_COMMAND_URL, headers=PRC_HEADERS, json={"command": command}
            )
            if status == 429:
                retry_after = 5.0
                if isinstance(resp, dict):
                    try:
                        retry_after = float(resp.get("retry_after", 5.0))
                    except (TypeError, ValueError):
                        pass
                log.warning("[Phone] Command rate limited, waiting %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                continue
            if status != 200:
                log.warning("[Phone] Command failed (%s): %s -> %s", status, command, resp)
            return status
        return 429

    # ----------------------------------------------------------- webhook entry

    @commands.Cog.listener()
    async def on_prc_webhook_event(self, payload: dict):
        """Handle a PRC Event Webhook payload.

        Observed shape:
            {"events": [{"event": "CustomCommand",
                         "origin": "1397037210",          # Roblox user id
                         "timestamp": 1783679947,
                         "data": {"command": "call", "argument": "pernambucado2"}}],
             "server": "..."}
        """
        try:
            events = payload.get("events")
            if not isinstance(events, list):
                log.info("[Phone] Ignoring webhook payload with no events list: %s", payload)
                return
            for event in events:
                if not isinstance(event, dict):
                    continue
                if event.get("event") != "CustomCommand":
                    continue
                data = event.get("data")
                if not isinstance(data, dict):
                    continue
                command = data.get("command")
                if not isinstance(command, str) or not command.strip():
                    continue
                body = command.strip()
                argument = data.get("argument")
                if isinstance(argument, str) and argument.strip():
                    body += " " + argument.strip()

                origin = str(event.get("origin", "")).strip()
                player = await self._resolve_origin(origin)
                if not player:
                    log.warning("[Phone] Could not resolve origin %r to a username (event: %s)", origin, event)
                    continue
                await self._route_command(player, body)
        except Exception:
            log.exception("[Phone] Error handling webhook payload: %s", payload)

    async def _resolve_origin(self, user_id: str) -> str | None:
        """Resolve a Roblox user id from a webhook `origin` to a username."""
        if not user_id or not user_id.isdigit():
            return None
        cached = self._username_cache.get(user_id)
        if cached:
            return cached

        # Primary: the Roblox users API (same helper the ERLC cog uses).
        # It returns the id itself when resolution fails, so treat that as a miss.
        try:
            resolved = await _resolve_roblox_users([user_id])
            name = resolved.get(user_id)
            if name and name != user_id:
                self._username_cache[user_id] = name
                return name
        except Exception:
            log.exception("[Phone] Roblox API lookup failed for %s", user_id)

        # Fallback: the in-game players list carries "Name:Id" pairs, and the
        # sender must be in-game to have typed the command.
        await self._refresh_players_cache()
        return self._username_cache.get(user_id)

    async def _refresh_players_cache(self):
        try:
            status, data = await api_get(PRC_PLAYERS_URL, headers=KEY_HEADERS)
        except Exception:
            log.exception("[Phone] Failed to fetch players list for cache refresh")
            return
        if status != 200 or not isinstance(data, list):
            return
        for entry in data:
            raw = entry.get("Player") if isinstance(entry, dict) else None
            if isinstance(raw, str) and ":" in raw:
                name, _, pid = raw.rpartition(":")
                if name.strip() and pid.strip().isdigit():
                    self._username_cache[pid.strip()] = name.strip()

    # ---------------------------------------------------------------- routing

    async def _route_command(self, player: str, body: str):
        if not body:
            return
        player_key = player.lower()
        parts = body.split()
        cmd = parts[0].lower()

        if cmd == "call":
            if len(parts) < 2:
                self._queue_pm(player, "Usage: ;call {username} to call someone, or ;call end to hang up.")
            elif parts[1].lower() == "end":
                await self._end_call(player, player_key)
            else:
                await self._initiate_call(player, player_key, parts[1])
        elif cmd == "calladd":
            if len(parts) < 2:
                self._queue_pm(player, "Usage: ;calladd {username}")
            else:
                await self._add_to_call(player, player_key, parts[1])
        elif cmd == "tagged":
            await self._report_tagged(player, player_key)
        elif cmd == "accept":
            await self._accept_call(player, player_key)
        elif cmd == "decline":
            await self._decline_call(player, player_key)
        elif cmd == "block":
            if len(parts) < 2:
                self._queue_pm(player, "Usage: ;block {username}")
            else:
                await self._block_user(player, player_key, parts[1])
        elif cmd == "unblock":
            if len(parts) < 2:
                self._queue_pm(player, "Usage: ;unblock {username}")
            else:
                await self._unblock_user(player, player_key, parts[1])
        else:
            await self._relay_message(player, player_key, body)

    # ------------------------------------------------------------- call logic

    async def _initiate_call(self, player: str, player_key: str, raw_target: str):
        target_query = raw_target.lstrip("@")
        if target_query.lower() == player_key:
            self._queue_pm(player, "You cannot call yourself.")
            return
        if self.data["members"].get(player_key):
            self._queue_pm(player, "You are already in a call. Use ;calladd to invite someone, or ;call end to hang up.")
            return
        if player_key in self.pending_out:
            self._queue_pm(player, "You already have an outgoing call ringing. Use ;call end to cancel it.")
            return
        if player_key in self.pending:
            self._queue_pm(player, "Someone is calling you right now. Use ;accept or ;decline first.")
            return

        target = await self._find_ingame_player(target_query)
        if target is None:
            self._queue_pm(player, f"Could not find {target_query} in the server. They must be in-game to receive a call.")
            return
        target_key = target.lower()
        if target_key == player_key:
            self._queue_pm(player, "You cannot call yourself.")
            return

        if self._is_blocked(player_key, target_key):
            self._queue_pm(player, "You cannot call this user.")
            return
        if self._is_busy(target_key):
            self._queue_pm(player, f"{target} is busy on another call right now.")
            return

        self.pending[target_key] = {
            "from": player, "from_key": player_key, "to": target,
            "created": time.time(), "call_id": None,
        }
        self.pending_out[player_key] = target_key
        self._queue_pm(target, f"Incoming Call from {player}. To accept, use ;accept. To decline, use ;decline.")
        self._queue_pm(player, f"Calling {target}... They have {RING_TIMEOUT} seconds to answer.")

    async def _add_to_call(self, player: str, player_key: str, raw_target: str):
        call_id, group = self._group_of(player_key)
        if group is None:
            self._queue_pm(player, "You are not in a call. Use ;call {username} to start one.")
            return
        if len(group["members"]) >= MAX_CALL_MEMBERS:
            self._queue_pm(player, f"This call is full ({MAX_CALL_MEMBERS} people max).")
            return
        if player_key in self.pending_out:
            self._queue_pm(player, "You already have an invite ringing. Wait for it to be answered or expire.")
            return

        target_query = raw_target.lstrip("@")
        if target_query.lower() == player_key:
            self._queue_pm(player, "You cannot add yourself.")
            return
        if target_query.lower() in group["members"]:
            self._queue_pm(player, f"{target_query} is already in this call.")
            return

        target = await self._find_ingame_player(target_query)
        if target is None:
            self._queue_pm(player, f"Could not find {target_query} in the server. They must be in-game to join a call.")
            return
        target_key = target.lower()
        if target_key == player_key:
            self._queue_pm(player, "You cannot add yourself.")
            return
        if target_key in group["members"]:
            self._queue_pm(player, f"{target} is already in this call.")
            return

        # A block between the target and ANY current member prevents the invite.
        if any(self._is_blocked(member_key, target_key) for member_key in group["members"]):
            self._queue_pm(player, "You cannot add this user to the call.")
            return
        if self._is_busy(target_key):
            self._queue_pm(player, f"{target} is busy on another call right now.")
            return

        self.pending[target_key] = {
            "from": player, "from_key": player_key, "to": target,
            "created": time.time(), "call_id": call_id,
        }
        self.pending_out[player_key] = target_key
        self._queue_pm(target, f"Incoming Call from {player}. To accept, use ;accept. To decline, use ;decline.")
        self._queue_pm(player, f"Inviting {target} to the call... They have {RING_TIMEOUT} seconds to answer.")

    async def _accept_call(self, player: str, player_key: str):
        ring = self.pending.pop(player_key, None)
        if ring is None:
            self._queue_pm(player, "You have no incoming call to accept.")
            return
        initiator = ring["from"]
        initiator_key = ring["from_key"]
        self.pending_out.pop(initiator_key, None)
        now = time.time()

        if ring["call_id"] is not None:
            # Invite into an existing group call.
            group = self.data["groups"].get(ring["call_id"])
            if group is None or initiator_key not in group["members"]:
                self._queue_pm(player, "That call has already ended.")
                return
            others = self._others(group, "")  # everyone currently in the call
            group["members"][player_key] = player
            group["last_activity"] = now
            self.data["members"][player_key] = ring["call_id"]
            self._save()
            self._queue_pm(others, f"{player} joined the call.")
            self._queue_pm(player, f"You joined the call with {', '.join(others)}. Send ;{{message}} to talk. Use ;call end to leave.")
            return

        # Regular two-person call.
        call_id = uuid.uuid4().hex[:8]
        self.data["groups"][call_id] = {
            "members": {initiator_key: initiator, player_key: player},
            "started": now,
            "last_activity": now,
        }
        self.data["members"][initiator_key] = call_id
        self.data["members"][player_key] = call_id
        self._save()
        self._queue_pm(initiator, f"{player} answered your call. Send ;{{message}} to talk. Use ;call end to hang up.")
        self._queue_pm(player, f"Call connected with {initiator}. Send ;{{message}} to talk. Use ;call end to hang up.")

    async def _decline_call(self, player: str, player_key: str):
        ring = self.pending.pop(player_key, None)
        if ring is None:
            self._queue_pm(player, "You have no incoming call to decline.")
            return
        self.pending_out.pop(ring["from_key"], None)
        # Per spec: only the initiator is notified on decline.
        self._queue_pm(ring["from"], "The call recipient declined your call.")

    async def _relay_message(self, player: str, player_key: str, body: str):
        _call_id, group = self._group_of(player_key)
        if group is None:
            # Not in a call: stay silent so other ;-command integrations aren't spammed.
            return
        group["last_activity"] = time.time()
        group["last_sender"] = player_key
        self._save()
        others = self._others(group, player_key)
        self._queue_pm(others, f"{player}: {body}")

    async def _report_tagged(self, player: str, player_key: str):
        _call_id, group = self._group_of(player_key)
        if group is None:
            self._queue_pm(player, "You are not in a call.")
            return
        # Notify the last person who spoke (their message is the one that got
        # tagged); fall back to everyone else if nobody has spoken yet.
        last_sender = group.get("last_sender")
        if last_sender and last_sender != player_key and last_sender in group["members"]:
            recipients = [group["members"][last_sender]]
        else:
            recipients = self._others(group, player_key)
        self._queue_pm(recipients, "Your last message may have been tagged. Please resend it.")

    async def _end_call(self, player: str, player_key: str):
        # Cancel an outgoing ring/invite if one exists.
        ring_target_key = self.pending_out.pop(player_key, None)
        if ring_target_key is not None:
            ring = self.pending.pop(ring_target_key, None)
            self._queue_pm(player, "Outgoing call cancelled.")
            if ring is not None:
                self._queue_pm(ring.get("to", ring_target_key), f"{player} cancelled the call.")
            if player_key not in self.data["members"]:
                return
            # If they were inviting someone into a group call, fall through so
            # ;call end also leaves the call itself.

        call_id, group = self._group_of(player_key)
        if group is None:
            if ring_target_key is None:
                self._queue_pm(player, "You are not in a call.")
            return

        others_keys = [k for k in group["members"] if k != player_key]
        self._remove_member(call_id, group, player_key)
        self._save()

        if call_id in self.data["groups"]:
            # Call continues without them.
            self._queue_pm(player, "You left the call.")
            self._queue_pm(self._others(self.data["groups"][call_id], player_key), f"{player} left the call.")
        else:
            other_names = [group["members"].get(k, k) for k in others_keys] or ["?"]
            self._queue_pm(player, f"Call with {', '.join(other_names)} ended.")
            self._queue_pm(other_names, f"Call ended. {player} hung up.")

    async def _block_user(self, player: str, player_key: str, raw_target: str):
        target = raw_target.lstrip("@")
        target_key = target.lower()
        if target_key == player_key:
            self._queue_pm(player, "You cannot block yourself.")
            return

        blocked = self.data["blocks"].setdefault(player_key, [])
        if target_key not in blocked:
            blocked.append(target_key)

        # Tear down any ring between the two players.
        if self.pending.get(player_key, {}).get("from_key") == target_key:
            self.pending.pop(player_key, None)
            self.pending_out.pop(target_key, None)
        if self.pending_out.get(player_key) == target_key:
            self.pending_out.pop(player_key, None)
            self.pending.pop(target_key, None)

        # If they're in the same two-person call, end it. Larger group calls
        # are left alone; the block only prevents future calls/invites.
        call_id, group = self._group_of(player_key)
        if group and target_key in group["members"] and len(group["members"]) == 2:
            target_name = group["members"][target_key]
            self.data["groups"].pop(call_id, None)
            self.data["members"].pop(player_key, None)
            self.data["members"].pop(target_key, None)
            self._queue_pm(target_name, f"Call ended. {player} hung up.")

        self._save()
        self._queue_pm(player, f"You have blocked {target}. Calls between you and them are no longer allowed.")

    async def _unblock_user(self, player: str, player_key: str, raw_target: str):
        target = raw_target.lstrip("@")
        target_key = target.lower()
        blocked = self.data["blocks"].get(player_key, [])
        if target_key in blocked:
            blocked.remove(target_key)
            self._save()
            self._queue_pm(player, f"You have unblocked {target}.")
        else:
            self._queue_pm(player, f"{target} is not on your block list.")

    # -------------------------------------------------------------- utilities

    async def _find_ingame_player(self, query: str) -> str | None:
        """Resolve a username (case-insensitive, unique-prefix allowed) to the
        exact in-game name via the PRC players list."""
        try:
            status, data = await api_get(PRC_PLAYERS_URL, headers=KEY_HEADERS)
        except Exception:
            log.exception("[Phone] Failed to fetch players list")
            return None
        if status != 200 or not isinstance(data, list):
            log.warning("[Phone] Players list fetch returned %s", status)
            return None

        names = []
        for entry in data:
            if isinstance(entry, dict) and isinstance(entry.get("Player"), str):
                raw = entry["Player"]
                name, _, pid = raw.rpartition(":")
                name = name.strip() if name else raw.strip()
                names.append(name)
                if name and pid.strip().isdigit():
                    self._username_cache[pid.strip()] = name

        query_lower = query.lower()
        for name in names:
            if name.lower() == query_lower:
                return name
        prefix_matches = [name for name in names if name.lower().startswith(query_lower)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        return None

    # ------------------------------------------------------------ maintenance

    @tasks.loop(seconds=30)
    async def call_maintenance(self):
        now = time.time()

        # Expire unanswered rings/invites.
        for target_key, ring in list(self.pending.items()):
            if now - ring["created"] >= RING_TIMEOUT:
                self.pending.pop(target_key, None)
                self.pending_out.pop(ring["from_key"], None)
                self._queue_pm(ring["from"], f"{ring.get('to', target_key)} did not answer your call.")

        # End calls inactive for 5+ minutes.
        changed = False
        for call_id, group in list(self.data["groups"].items()):
            if now - group["last_activity"] < CALL_INACTIVITY_TIMEOUT:
                continue
            member_names = list(group["members"].values())
            for member_key in list(group["members"]):
                self.data["members"].pop(member_key, None)
            self.data["groups"].pop(call_id, None)
            changed = True
            self._queue_pm(member_names, "Call ended automatically after 5 minutes of inactivity.")
        if changed:
            self._save()

    @call_maintenance.before_loop
    async def before_call_maintenance(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(PhoneSystem(bot))
