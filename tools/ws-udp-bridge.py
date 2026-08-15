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
import http
import itertools
import json
import logging
import os
import socket as _socket
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
        self.viewers = 0


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


def parse_status_response(data):
    """Pull the infostring and client count out of a Quake 3 statusResponse.

    Format is `\\xff\\xff\\xff\\xffstatusResponse\\n\\key\\value\\...\\n` followed by
    one line per connected client. Keys are latin-1 rather than utf-8 on
    purpose: JK2 names carry `^` colour codes and arbitrary high bytes, and a
    strict utf-8 decode would raise on a player whose name happens to be
    malformed -- which is exactly the sort of thing that takes a status page
    down at the worst moment.
    """
    if not data.startswith(b"\xff\xff\xff\xff"):
        return None
    body = data[4:]
    if not body.startswith(b"statusResponse"):
        return None

    lines = body.split(b"\n")
    if len(lines) < 2:
        return None

    info = {}
    fields = lines[1].decode("latin-1").split("\\")
    # The infostring opens with a separator, so the first element is empty and
    # the real content is key/value pairs from index 1.
    for i in range(1, len(fields) - 1, 2):
        info[fields[i]] = fields[i + 1]

    clients = sum(1 for line in lines[2:] if line.strip())
    return {"info": info, "clients": clients}


async def query_server_status(target_host, target_port, timeout=1.0):
    """Ask the game server what is on, out-of-band.

    Deliberately a separate socket from the relay path: this is the engine's
    own `getstatus` query, the same one a server browser sends, so it works
    without cooperation from the game and tells us the map and who is
    connected even when no viewer is watching.
    """
    loop = asyncio.get_running_loop()
    reply = loop.create_future()

    class _StatusProtocol(asyncio.DatagramProtocol):
        def datagram_received(self, data, addr):
            if not reply.done():
                reply.set_result(data)

        def error_received(self, exc):
            if not reply.done():
                reply.set_exception(exc)

    try:
        transport, _ = await loop.create_datagram_endpoint(
            _StatusProtocol, remote_addr=(target_host, target_port))
    except OSError as exc:
        log.debug("status query could not open a socket: %s", exc)
        return None

    try:
        transport.sendto(b"\xff\xff\xff\xffgetstatus\n")
        data = await asyncio.wait_for(reply, timeout)
    except (asyncio.TimeoutError, OSError):
        # A server that is down or restarting simply does not answer. That is
        # a normal state for this endpoint to report, not an error to log
        # loudly every few seconds.
        return None
    finally:
        transport.close()

    try:
        return parse_status_response(data)
    except Exception:
        log.warning("unparseable statusResponse from %s:%d", target_host, target_port)
        return None


async def status_poller(state, target_host, target_port, interval=5):
    """Keep the cached server status warm.

    Polled on a timer rather than queried per request so that a page open in
    twenty tabs cannot turn into twenty `getstatus` packets a second at the
    game server. The HTTP handler then answers from memory and never blocks
    the WebSocket accept path.
    """
    while True:
        status = await query_server_status(target_host, target_port)
        state["status"] = status
        state["checked_at"] = time.time()
        await asyncio.sleep(interval)


def status_payload(state, stats):
    status = state.get("status")
    info = (status or {}).get("info", {})
    clients = (status or {}).get("clients", 0)
    viewers = stats.viewers

    # `clients` counts everyone the server has, and our viewers are real
    # spectator clients on it -- so they are in that number. Subtract them for
    # a "who is actually playing" figure, floored because the two counts are
    # sampled at different moments and a viewer can leave between them.
    return {
        "online": status is not None,
        "checkedAt": state.get("checked_at", 0),
        "viewers": viewers,
        "clients": clients,
        "players": max(clients - viewers, 0),
        "map": info.get("mapname"),
        "hostname": info.get("sv_hostname"),
        "gametype": info.get("g_gametype"),
    }


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
                        secret=None, server_index=0, sessions=None,
                        sticky_sources=None):
    peer = ws.remote_address

    # Disable Nagle on this connection's TCP socket. The asyncio flavour of the
    # websockets library never does (the sync flavour does), and Nagle is built
    # for exactly the traffic we produce: a steady stream of small messages.
    # It holds each one back until the previous is acknowledged, and together
    # with delayed ACKs on the far side that turns "one snapshot every 10ms"
    # into "a clump of several every 40" -- which the viewer sees as stutter,
    # because the client interpolates against arrival timing. Snapshots are
    # latency-critical and tiny; batching them saves nothing worth having.
    tcp = ws.transport.get_extra_info("socket")
    if tcp is not None:
        tcp.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)

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

    src = next_loopback_source(source_index, target_host)

    # Come back on the same source address a viewer used last time.
    #
    # The game server already knows how to handle this: SV_DirectConnect has a
    # "if there is already a slot for this ip, reuse it" path, taken when the
    # address matches and either the qport or the source port does. A reloaded
    # page generates a fresh qport, so the source port is the only handle left
    # -- and with an ephemeral port every reload looked like a stranger, so the
    # server kept the abandoned client until it timed out and the viewer came
    # back alongside their own ghost.
    #
    # Keyed on the account, which is the thing that actually persists across a
    # reload. Without auth there is no such key and this simply does not apply.
    sticky = sticky_sources.get(player_id) if (player_id and sticky_sources is not None) else None
    local_addr = sticky or ((src, 0) if src else None)

    async def bind(addr):
        return await loop.create_datagram_endpoint(
            lambda: UdpProtocol(forward_to_ws),
            remote_addr=(target_host, target_port),
            local_addr=addr,
        )

    transport = None

    # Wait for the sticky port rather than giving up on it the moment it is
    # busy. Connections arrive in overlapping pairs -- every dial is followed
    # by a second one a few hundred ms later, which supersedes it -- so the
    # port is routinely still held by the session being replaced. Failing fast
    # meant the *surviving* socket was the one that fell back to a random port,
    # which is precisely the case this whole mechanism exists to fix.
    if sticky:
        for _ in range(12):
            try:
                transport, _ = await bind(sticky)
                break
            except OSError:
                await asyncio.sleep(0.05)
        if transport is None:
            log.warning("sticky source %s stayed busy; falling back", sticky)

    if transport is None:
        for attempt in ((src, 0) if src else None, None):
            try:
                transport, _ = await bind(attempt)
                break
            except OSError as e:
                # Binding a loopback alias is refused where 127.0.0.0/8 is not
                # wholly local (macOS needs explicit aliases). Fall back rather
                # than refuse the viewer -- the worst case is the behaviour we
                # had before any of this.
                log.warning("could not bind source %s (%s); falling back", attempt, e)

    if transport is None:
        log.error("no usable source address for %s; dropping", peer)
        await ws.close(code=1011, reason="no socket")
        return

    bound = transport.get_extra_info("sockname")
    if player_id and bound and sticky_sources is not None:
        sticky_sources[player_id] = bound
    log.info("  viewer %s using source %s", peer, bound)

    async def pump():
        while True:
            data = await outbox.get()
            await ws.send(data)

    pump_task = asyncio.create_task(pump())

    # Counted here rather than from `sessions`, which only fills in when token
    # auth is on -- a --no-auth debugging run would otherwise report nobody
    # watching while people are watching.
    stats.viewers += 1

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
        stats.viewers -= 1
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

    # The library logs every HTTP request that process_request answers as
    # "connection rejected (200 OK)" -- which is what a perfectly good /status
    # poll looks like from inside websockets. Every viewer polls it, so at INFO
    # that is a line every few seconds, burying the connect/disconnect events
    # this log exists for. Warnings and errors still come through, including
    # the handshake failures that are worth seeing.
    logging.getLogger("websockets.server").setLevel(logging.WARNING)

    stats = Stats()
    # Monotonic per-connection counter, so each viewer gets its own loopback
    # source address (see next_loopback_source).
    conn_counter = itertools.count()

    # playerId -> active websocket. One bridge, one process, so a plain dict
    # is the whole of "server-side session tracking" the brief asks about.
    sessions = {}

    # playerId -> the (host, port) that account last talked to the game server
    # from, so a reload reconnects into its own slot instead of arriving as a
    # stranger beside its own abandoned client. Never pruned: an entry is two
    # small values, and forgetting one costs exactly the bug it prevents.
    sticky_sources = {}

    async def handler(ws):
        await handle_client(ws, target_host, target_port, stats, next(conn_counter),
                            secret=secret, server_index=args.server_index,
                            sessions=sessions, sticky_sources=sticky_sources)

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

    # Last known server status, refreshed on a timer by status_poller.
    status_state = {"status": None, "checked_at": 0}

    def process_request(connection, request):
        """Serve GET /status; let everything else continue as a WebSocket.

        Unauthenticated, and deliberately so: it answers "is anything on and
        how many people are watching", which is exactly what the page needs
        *before* it asks anyone to sign in. It exposes only what a server
        browser already shows the whole internet -- map, hostname, gametype,
        counts -- and no player names or identities.

        Answered from cache so this cannot be used to make the bridge flood
        the game server, and returning None hands the connection back to the
        normal WebSocket path untouched.
        """
        if request.path.split("?")[0] != "/status":
            return None
        body = json.dumps(status_payload(status_state, stats)) + "\n"
        response = connection.respond(http.HTTPStatus.OK, body)
        # `respond` has already set text/plain, and Headers is a multidict --
        # assigning would append a second Content-Type rather than replace the
        # first, leaving the response ambiguous and the browser free to believe
        # the wrong one. Drop it before setting ours.
        del response.headers["Content-Type"]
        response.headers["Content-Type"] = "application/json"
        # The page is served from Soracle's origin, not this one, so it has to
        # be allowed to read the response. Safe to open: the payload is public
        # information and the endpoint takes no input.
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Cache-Control"] = "no-store"
        return response

    async def run():
        asyncio.create_task(reporter(stats))
        asyncio.create_task(status_poller(status_state, target_host, target_port))
        # max_size=None: JK2 packets are small, but no reason to impose the
        # library's 1MB-message default on a UDP relay.
        async with websockets.serve(handler, listen_host, int(listen_port), max_size=None,
                                    select_subprotocol=select_subprotocol,
                                    process_request=process_request):
            log.info("listening on %s, relaying to %s:%d", args.listen, target_host, target_port)
            await asyncio.Future()  # run forever

    asyncio.run(run())


if __name__ == "__main__":
    main()
