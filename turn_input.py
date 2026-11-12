"""Read one turn at a time while keeping text prompts in line mode."""

import os
import sys


PASTED_MOVE = "PASTED_MOVE"

def _read_command(read_key, prompt):
    while True:
        print("\r\033[2K" + prompt, end="", flush=True)
        key = read_key()
        if key in ("", "\x04", "X"):
            return "X"
        if key in ("\r", "\n", "\x1b"):
            continue
        if key != "F":
            if len(key) == 1 and key.isprintable():
                print(key, end="", flush=True)
            return key

        print("\r\033[2KAim [WASD, Esc to cancel] > ", end="", flush=True)
        direction = read_key()
        if direction in ("", "\x04", "X"):
            return "X"
        if direction == PASTED_MOVE:
            return PASTED_MOVE
        if direction in ("W", "A", "S", "D"):
            return "F" + direction
        if direction not in ("\r", "\n", "\x1b"):
            return "F?"


def _read_windows_key():
    import msvcrt

    key = msvcrt.getwch()
    if key in ("\x00", "\xe0"):
        # Windows reports arrows and other special keys as two characters.
        msvcrt.getwch()
        return "\x1b"
    return key.upper()


def read_turn(prompt="Move [WASD | F + direction | E | T | H | X] > "):
    if not sys.stdin.isatty() or os.name not in ("nt", "posix"):
        try:
            return input("Enter your move: ").strip().upper()
        except EOFError:
            return "X"
    if os.name == "nt":
        return _read_command(_read_windows_key, prompt)

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)

    pending_key = b""

    def discard_paste():
        # Terminals that support bracketed paste send an end marker.
        end_marker = b"\x1b[201~"
        tail = b""
        while select.select([fd], [], [], 1)[0]:
            part = os.read(fd, 1)
            if not part:
                break
            tail = (tail + part)[-len(end_marker):]
            if tail == end_marker:
                break

    def read_key():
        nonlocal pending_key
        key = pending_key or os.read(fd, 1)
        pending_key = b""
        if key != b"\x1b":
            return key.decode("ascii", errors="replace").upper()

        # Consume terminal escape sequences so an arrow's final letter
        # cannot become a movement command.
        if select.select([fd], [], [], 0.03)[0]:
            prefix = os.read(fd, 1)
            if prefix in (b"[", b"O"):
                sequence = prefix
                while select.select([fd], [], [], 0.03)[0]:
                    part = os.read(fd, 1)
                    if not part:
                        break
                    if len(sequence) < 8:
                        sequence += part
                    if b"@" <= part <= b"~":
                        break
                if sequence == b"[200~":
                    discard_paste()
                    return PASTED_MOVE
            else:
                pending_key = prefix
        return "\x1b"

    try:
        tty.setcbreak(fd, termios.TCSANOW)
        print("\033[?2004h", end="", flush=True)
        return _read_command(read_key, prompt)
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, original)
        print("\033[?2004l", end="", flush=True)
