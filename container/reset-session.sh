#!/bin/bash
set -eu

# Tell the restarted launcher to bring up Dream Seeker as well as the pager.
XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}"
: >"$XDG_RUNTIME_DIR/byond-reset-requested"
exec s6-svc -k /etc/service/byond
