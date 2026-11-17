#!/bin/sh
set -eu

exec "$GE_PROTON_PATH/proton" run "$@"
