#!/bin/bash
set -eu

exec s6-svc -k /etc/service/byond
