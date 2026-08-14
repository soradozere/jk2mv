#!/usr/bin/env python3
"""Client-side mirror of ws-udp-bridge.py: local UDP in, WebSocket out.

Diagnostic only. Lets a NATIVE JK2 client speak to the remote
WebSocket<->UDP bridge, which it otherwise cannot do -- the game speaks UDP
and the bridge speaks WebSocket. Point the game at this script's local port
and it reaches the same bridge the browser uses.

The point is to split a failure that currently has two suspects. A native
client connecting straight to the game server works; the browser through the
bridge dies parsing entities. Running native THROUGH the bridge separates
"the bridge mangles the stream" from "the wasm client mishandles it":

    native -> game server           : works (established)
    native -> bridge -> game server : THIS SCRIPT
    browser -> bridge -> game server: fails

Usage:
    python3 udp-ws-client-bridge.py --listen 28071 --bridge ws://HOST:8080
then in the game console:  /connect 127.0.0.1:28071
"""
import argparse
import asyncio
import logging

import websockets

log = logging.getLogger("udp-ws-client")


async def main_async(listen_port, bridge_url, bind_addr):
    loop = asyncio.get_running_loop()
    # Where the game client last sent from; replies go back there. One client
    # only -- this is a diagnostic, not infrastructure.
    client_addr = None
    to_bridge = asyncio.Queue()

    class GameProtocol(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            nonlocal client_addr
            if client_addr != addr:
                log.info("game client at %s", addr)
                client_addr = addr
            to_bridge.put_nowait(data)

    transport, _ = await loop.create_datagram_endpoint(
        GameProtocol, local_addr=(bind_addr, listen_port)
    )
    log.info("listening on udp %s:%d -> %s", bind_addr, listen_port, bridge_url)
    log.info("in the game console:  /connect 127.0.0.1:%d", listen_port)

    while True:
        try:
            async with websockets.connect(bridge_url, max_size=None) as ws:
                log.info("bridge connected")

                async def pump_out():
                    # Serialised, same reasoning as the server-side bridge:
                    # one task owns the socket so ordering is preserved.
                    while True:
                        data = await to_bridge.get()
                        await ws.send(data)

                out = asyncio.create_task(pump_out())
                try:
                    async for msg in ws:
                        if isinstance(msg, str):
                            msg = msg.encode()
                        if client_addr:
                            transport.sendto(msg, client_addr)
                finally:
                    out.cancel()
        except Exception as e:
            log.warning("bridge connection lost (%s); retrying in 2s", e)
            await asyncio.sleep(2)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--listen", type=int, default=28071,
                   help="local UDP port for the game client to connect to")
    p.add_argument("--bind", default="127.0.0.1",
                   help="address to bind on; 0.0.0.0 to accept a game client "
                        "on another machine (e.g. a Steam Deck on the same LAN)")
    p.add_argument("--bridge", required=True,
                   help="ws://host:port of the remote bridge")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(main_async(args.listen, args.bridge, args.bind))


if __name__ == "__main__":
    main()
