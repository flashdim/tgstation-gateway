#!/usr/bin/env python3

import json
import os
import socket
import sys

if len(sys.argv) != 2 or sys.argv[1] not in {"connected", "disconnected"}:
    raise SystemExit(2)

path = os.environ.get("GATEWAY_CONTROLLER_SOCKET")
if not path:
    raise SystemExit(0)

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
    channel.settimeout(2)
    channel.connect(path)
    channel.sendall((json.dumps(sys.argv[1]) + "\n").encode())
