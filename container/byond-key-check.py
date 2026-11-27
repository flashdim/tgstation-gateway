#!/usr/bin/env python3
"""Exit 0 when BYOND's key.txt holds a complete key block for the account."""

import os
import re
import stat
import sys

KEY_HEADER = re.compile(rb"^\[?BEGIN KEY[ \t]+([A-Za-z0-9_-]{1,48})\]?$", re.I)
KEY_END = re.compile(rb"^\[?END KEY\]?$", re.I)
MAX_KEY_BYTES = 1024 * 1024


def key_matches(path, account):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                return False, "BYOND key.txt is not a regular file"
            data = file.read(MAX_KEY_BYTES + 1)
    except FileNotFoundError:
        return False, "BYOND key.txt is missing"
    except OSError as error:
        return (
            False,
            f"Cannot read BYOND key.txt: {error.strerror or type(error).__name__}",
        )
    if len(data) > MAX_KEY_BYTES:
        return False, "BYOND key.txt is too large to check"

    expected = account.encode("ascii").lower()
    matching = False
    has_data = False
    for line in data.splitlines():
        line = line.strip()
        header = KEY_HEADER.fullmatch(line)
        if header:
            matching = header.group(1).lower() == expected
            has_data = False
        elif KEY_END.fullmatch(line):
            if matching and has_data:
                return True, ""
            matching = False
        elif matching and line:
            has_data = True
    return False, f"BYOND key.txt has no complete key for {account}"


def main(argv):
    if len(argv) != 3 or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", argv[2]):
        print("usage: byond-key-check.py KEY_FILE ACCOUNT", file=sys.stderr)
        return 2
    matches, reason = key_matches(argv[1], argv[2])
    if not matches:
        print(f"{reason}; log in as {argv[2]} and save the password", file=sys.stderr)
    return 0 if matches else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
