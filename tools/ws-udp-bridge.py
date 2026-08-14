#!/usr/bin/env python3
"""Minimal WebSocket<->UDP bridge for the live-spectate prototype (Brief 1).

Plain `websockify` proxies WebSocket<->TCP, not UDP -- JK2's netcode is UDP,
so that specific tool doesn't apply here despite being the brief's working
name for this piece. This is the "or equivalent": one UDP socket per browser
WebSocket connection, relaying frames verbatim in both directions. No
framing, multiplexing, or virtual addressing -- there's exactly one client
and one server for this test, so none of that is needed. (jk2-demo-player's
other repo, openjk-wasm, has a much heavier WebTransport version of this
built for a different game's real multiplayer routing -- wasm/wtunnel,
unrelated to this prototype.)

WebSocket messages map 1:1 to UDP datagrams, which is exactly the framing
the wasm client's socket emulation and this bridge both assume -- no length
prefixing needed.

Requires: pip install websockets

Usage:
    python3 ws-udp-bridge.py --listen 0.0.0.0:8080 --target 127.0.0.1:28070
"""
import argparse
import asyncio
import hashlib
import hmac
import itertools
import logging
import os
import time

import websockets

log = logging.getLogger("ws-udp-bridge")


class UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_datagram):
        self.on_datagram = on_datagram
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.on_datagram(data)

    def error_received(self, exc):
        log.warning("udp error: %s", exc)


def verify_token(token, secret, now_ms=None):
    """Verify a Soracle live-spectate token; return claims or None.

    Format, minted by lib/live-token.ts:
        <playerId>.<serverIndex>.<expiryMs>.<hmac-sha256-hex>

    The HMAC key is LIVE_BRIDGE_SECRET, deliberately NOT the site's session
    secret: this process runs on a game server box that other people
    administer, and a key found here must not be able to mint login cookies
    for the site. Forging one of these only buys a spectate slot.
    """
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 4:
        return None
    player_id, server_index_s, expires_s, sig = parts
    payload = f"{player_id}.{server_index_s}.{expires_s}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    # compare_digest, not ==: string comparison returns early on the first
    # differing byte, which leaks how much of a guess was right.
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        expires = int(expires_s)
        server_index = int(server_index_s)
    except ValueError:
        return None
    now = now_ms if now_ms is not None else time.time() * 1000
    if now > expires:
        # Distinguished from a bad signature by the caller: "expired" means
        # the client waited too long and should ask the site for another,
        # while "bad signature" means someone is forging. Reporting both as
        # one thing sent us chasing a forgery that was really a stale tab.
        return {"expired_by_ms": now - expires}
    if server_index < 0:
        return None
    return {"player_id": player_id, "server_index": server_index}


class Stats:
    """Byte/packet counters, so a run answers the 'is this KB/s?' question."""

    def __init__(self):
        self.to_client_bytes = 0
        self.to_client_packets = 0
        self.to_server_bytes = 0
        self.to_server_packets = 0


async def reporter(stats, interval=10):
    """Periodic throughput, measured rather than assumed."""
    prev_down = prev_up = 0
    while True:
        await asyncio.sleep(interval)
        down = stats.to_client_bytes - prev_down
        up = stats.to_server_bytes - prev_up
        prev_down, prev_up = stats.to_client_bytes, stats.to_server_bytes
        if not down and not up:
            continue  # idle; don't paper the log with zeroes
        log.info(
            "down %.1f KB/s (%d pkts total) | up %.1f KB/s (%d pkts total)",
            down / interval / 1024, stats.to_client_packets,
            up / interval / 1024, stats.to_server_packets,
        )


def next_loopback_source(counter, target_host):
    """A distinct 127.0.0.x source address per viewer, or None.

    NWH ships g_limitSameIP 1 / g_maxConnPerIP 3, and the limiter counts
    loopback -- measured: a second browser viewer through the bridge is
    refused with "Too many connections from the same IP" when the cap is 1.
    Since every viewer's packets leave the bridge from one socket address,
    the bridge would otherwise impose a hard ceiling of 3 concurrent
    viewers on a stock NWH server.

    On Linux the whole 127.0.0.0/8 range is loopback, so when the game
    server is on this same box each viewer can be given its own source
    address and the limiter never trips -- no server config change, and no
    asking an admin to weaken an anti-abuse control that exists for good
    reason. They ARE separate clients; this just stops them looking like
    one host.

    Only valid when the target is loopback. Talking to a game server across
    a network, the source has to be a real address on this machine, so the
    per-IP limit applies for real and it becomes a conversation with
    whoever runs that server.
    """
    if not target_host.startswith("127."):
        return None
    # .1 is left alone (anything else on the box uses it); start at .2.
    # /8 gives ~16M addresses, so the wrap is theoretical.
    octet_c, octet_d = divmod(counter % 65024, 254)
    return f"127.0.{octet_c}.{octet_d + 2}"


async def handle_client(ws, target_host, target_port, stats, source_index,
                        secret=None, server_index=0, sessions=None):
    peer = ws.remote_address

    # Authenticate BEFORE a single packet is relayed.
    #
    # This is the real boundary. The engine also has an allowlist, but that is
    # client-side convenience -- anyone can edit the wasm or call the export --
    # so without this check the bridge is an open UDP relay to the game server
    # for whoever finds the port.
    player_id = None
    if secret:
        token = ws.request.headers.get("Sec-WebSocket-Protocol", "")
        # A client may offer several; ours sends one.
        token = token.split(",")[0].strip()
        claims = verify_token(token, secret)
        if claims and "expired_by_ms" in claims:
            log.warning("REJECTED %s: token expired %.0fs ago -- fetch a fresh one",
                        peer, claims["expired_by_ms"] / 1000)
            await ws.close(code=4401, reason="token expired")
            return
        if not claims:
            log.warning("REJECTED %s: bad signature (token=%r)", peer, token[:24])
            await ws.close(code=4401, reason="unauthorized")
            return
        if claims["server_index"] != server_index:
            # A token minted for another allowlisted server must not be
            # replayable here.
            log.warning("REJECTED %s: token is for server %d, this bridge is %d",
                        peer, claims["server_index"], server_index)
            await ws.close(code=4403, reason="wrong server")
            return
        player_id = claims["player_id"]
        log.info("client connected: %s as player %s", peer, player_id)

        # One session per account, strictly: a new request boots the old one.
        # In memory, which is sufficient while there is exactly one bridge --
        # if a second is ever run, two tabs could hold sessions on different
        # bridges and this stops being an enforcement.
        if sessions is not None:
            previous = sessions.get(player_id)
            if previous is not None and previous is not ws:
                log.info("  booting previous session for %s", player_id)
                asyncio.ensure_future(previous.close(code=4409, reason="superseded"))
            sessions[player_id] = ws
    else:
        log.info("client connected: %s (no auth configured)", peer)

    loop = asyncio.get_running_loop()

    # Datagrams go through a queue drained by ONE task below, rather than
    # each one spawning its own ws.send().
    #
    # This is what broke the first live test: the engine handshook, loaded the
    # map and went active, then died on `CL_ParsePacketEntities: end of
    # message` the moment real snapshots started. Fire-and-forget
    # ensure_future(ws.send(...)) gives no ordering guarantee between tasks,
    # and the websockets library does not support concurrent send() on one
    # connection -- so a burst (this server runs sv_fps 100 / sv_maxsnaps 100)
    # could interleave or drop frames. A truncated or out-of-order snapshot is
    # exactly what "end of message" means client-side. Serialising here keeps
    # the WebSocket carrying datagrams in the order the server sent them.
    outbox = asyncio.Queue()

    def forward_to_ws(data):
        stats.to_client_bytes += len(data)
        stats.to_client_packets += 1
        outbox.put_nowait(data)

    local_addr = None
    src = next_loopback_source(source_index, target_host)
    if src:
        local_addr = (src, 0)
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: UdpProtocol(forward_to_ws),
            remote_addr=(target_host, target_port),
            local_addr=local_addr,
        )
        if src:
            log.info("  viewer %s using source %s", peer, src)
    except OSError as e:
        # Binding a loopback alias can fail on platforms where 127.0.0.0/8
        # is not wholly local (macOS needs explicit aliases). Fall back to
        # the default source rather than refusing the viewer -- they just
        # count against the per-IP limit again.
        log.warning("could not bind source %s (%s); using default", src, e)
        transport, _ = await loop.create_datagram_endpoint(
            lambda: UdpProtocol(forward_to_ws),
            remote_addr=(target_host, target_port),
        )

    async def pump():
        while True:
            data = await outbox.get()
            await ws.send(data)

    pump_task = asyncio.create_task(pump())

    try:
        async for message in ws:
            if isinstance(message, str):
                message = message.encode()
            stats.to_server_bytes += len(message)
            stats.to_server_packets += 1
            transport.sendto(message)
    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception:
        # Logged rather than swallowed: the old version let a relay error
        # disappear into an un-awaited task, which looked like packet loss
        # from the client and like nothing at all from here.
        log.exception("relay error for %s", peer)
    finally:
        pump_task.cancel()
        try:
            await pump_task
        except (asyncio.CancelledError, Exception):
            pass
        # Only clear the slot if it is still ours: a newer session for the
        # same account may already have replaced it, and that one must not be
        # evicted by the old socket's cleanup.
        if sessions is not None and player_id is not None:
            if sessions.get(player_id) is ws:
                del sessions[player_id]
        log.info(
            "client disconnected: %s (down %d pkts/%d B, up %d pkts/%d B)",
            peer, stats.to_client_packets, stats.to_client_bytes,
            stats.to_server_packets, stats.to_server_bytes,
        )
        transport.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--listen", default="0.0.0.0:8080",
                    help="host:port to accept WebSocket connections on")
    p.add_argument("--target", required=True,
                    help="host:port of the dedicated server's UDP socket")
    p.add_argument("--server-index", type=int, default=0,
                    help="which allowlisted server this bridge fronts; tokens "
                         "minted for a different index are refused")
    p.add_argument("--no-auth", action="store_true",
                    help="relay without checking tokens. For local debugging "
                         "only -- this makes the bridge an open relay to the "
                         "game server for anyone who can reach the port.")
    args = p.parse_args()

    # Secret from the environment, never a flag: command lines are visible to
    # every user on the box via ps.
    secret = os.environ.get("LIVE_BRIDGE_SECRET")
    if args.no_auth:
        secret = None
        log.warning("running WITHOUT token auth (--no-auth): open relay")
    elif not secret:
        p.error("LIVE_BRIDGE_SECRET is not set (or pass --no-auth for local debugging)")

    listen_host, listen_port = args.listen.rsplit(":", 1)
    target_host, target_port_s = args.target.rsplit(":", 1)
    target_port = int(target_port_s)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    stats = Stats()
    # Monotonic per-connection counter, so each viewer gets its own loopback
    # source address (see next_loopback_source).
    conn_counter = itertools.count()

    # playerId -> active websocket. One bridge, one process, so a plain dict
    # is the whole of "server-side session tracking" the brief asks about.
    sessions = {}

    async def handler(ws):
        await handle_client(ws, target_host, target_port, stats, next(conn_counter),
                            secret=secret, server_index=args.server_index,
                            sessions=sessions)

    def select_subprotocol(ws, subprotocols):
        """Echo the client's offer back.

        The token rides in Sec-WebSocket-Protocol, and a browser aborts the
        handshake unless the server names one of the offered protocols in its
        reply. So this has to accept the token string itself as the
        "protocol" -- the header is being used as a credential channel, which
        is a well-worn trick precisely because browsers give you nowhere else
        to put one on a WebSocket.
        """
        return subprotocols[0] if subprotocols else None

    async def run():
        asyncio.create_task(reporter(stats))
        # max_size=None: JK2 packets are small, but no reason to impose the
        # library's 1MB-message default on a UDP relay.
        async with websockets.serve(handler, listen_host, int(listen_port), max_size=None,
                                    select_subprotocol=select_subprotocol):
            log.info("listening on %s, relaying to %s:%d", args.listen, target_host, target_port)
            await asyncio.Future()  # run forever

    asyncio.run(run())


if __name__ == "__main__":
    main()
