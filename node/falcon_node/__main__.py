"""falcon-node command line.

    python3 -m falcon_node run      start the node (what falcon-node.service runs)
    python3 -m falcon_node check    show what hardware the node can see
    python3 -m falcon_node pairing  show the address and pairing key to enter in FALCON
"""

import argparse
import logging
import signal
import threading
from pathlib import Path
from urllib.parse import urlunsplit

from falcon_node import VERSION
from falcon_node.agent import Agent
from falcon_node.config import NodeConfig
from falcon_node.server import serve

DEFAULT_CONFIG = Path("/etc/falcon-node/node.conf")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="falcon-node", description="FALCON sensor node " + VERSION)
    parser.add_argument("command", nargs="?", default="run", choices=["run", "check", "pairing"])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="node.conf path")
    parser.add_argument("--state-dir", type=Path, help="override STATE_DIR (for testing)")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = NodeConfig.load(arguments.config if arguments.config.exists() else None, state_dir=arguments.state_dir)

    if arguments.command == "pairing":
        from falcon_node.system import addresses

        hosts = addresses() or ["<this node's address>"]
        print(f"Node:        {config.name} ({config.node_id})")
        print("Address:     " + urlunsplit(("http", f"{hosts[0]}:{config.api_port}", "", "", "")))
        print(f"Pairing key: {config.pairing_key}")
        print("Enter both in FALCON → Sensors → Add sensor node.")
        return 0

    agent = Agent(config)
    if arguments.command == "check":
        status = agent.status()
        for name, item in status["components"].items():
            label = item["description"] if item["present"] else "not detected"
            print(f"{name:11} {label}")
        print(f"{'board':11} {status['system']['board']}")
        print(f"{'clock':11} {'synchronized' if status['clock']['synchronized'] else 'not synchronized'}")
        return 0

    server = serve(agent)
    stopping = threading.Event()

    def shutdown(*_: object) -> None:
        stopping.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    agent.start()
    threading.Thread(target=server.serve_forever, daemon=True, name="falcon-node-api").start()
    logging.getLogger("falcon-node").info(
        "FALCON sensor node %s (%s) listening on port %d", config.name, config.node_id, config.api_port,
    )
    stopping.wait()
    server.shutdown()
    agent.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
