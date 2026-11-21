#!/bin/bash
set -eu

export PATH="/opt/wine-proton/bin:$PATH"
export WINELOADER="/opt/wine-proton/bin/wine"
export WINESERVER="/opt/wine-proton/bin/wineserver"

pkill -KILL -ix -u "$EUID" 'dreamseeker[.]exe|byond[.]exe|wineserver[.]exe' || true
timeout --kill-after=1s 5s wineserver -k9 || true
timeout --kill-after=1s 5s wineserver --wait
