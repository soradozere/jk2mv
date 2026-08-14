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
import logging

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


async def handle_client(ws, target_host, target_port, stats):
    peer = ws.remote_address
    log.info("client connected: %s", peer)
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
    args = p.parse_args()

    listen_host, listen_port = args.listen.rsplit(":", 1)
    target_host, target_port_s = args.target.rsplit(":", 1)
    target_port = int(target_port_s)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    stats = Stats()

    async def handler(ws):
        await handle_client(ws, target_host, target_port, stats)

    async def run():
        asyncio.create_task(reporter(stats))
        # max_size=None: JK2 packets are small, but no reason to impose the
        # library's 1MB-message default on a UDP relay.
        async with websockets.serve(handler, listen_host, int(listen_port), max_size=None):
            log.info("listening on %s, relaying to %s:%d", args.listen, target_host, target_port)
            await asyncio.Future()  # run forever

    asyncio.run(run())


if __name__ == "__main__":
    main()
