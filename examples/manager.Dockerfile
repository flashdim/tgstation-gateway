FROM docker:29.1.3-cli@sha256:4fa0ee1f3a7e4354c4ea34558b6d4ee32859baf4973d4c8ccc8e7fe3dd730c04

RUN apk add --no-cache grep

COPY examples/slot-manager.sh /usr/local/bin/slot-manager
COPY examples/seccomp.json /opt/gateway/seccomp.json
ENTRYPOINT ["sh", "/usr/local/bin/slot-manager"]
