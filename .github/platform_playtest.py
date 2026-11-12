import ast
import codecs
from collections import deque
import os
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Thread
from time import monotonic

import pyte

WINDOWS = os.name == "nt"
GAME = str(Path("movement_logic.py").resolve())
PROMPT = "Move [WASD"
SELECT = "Choose 1 or 2, then press Enter >"
ICON = "@" if WINDOWS else "☺"
ENTER = "\r" if WINDOWS else "\n"


class Game:
    def __enter__(self):
        self.screen = pyte.HistoryScreen(80, 24, history=500)
        self.stream = pyte.Stream(self.screen)
        self.output = Queue()
        self.env = dict(os.environ, TERM="xterm-256color", PYTHONIOENCODING="utf-8")
        self.env.pop("NO_COLOR", None)
        argv = [sys.executable, "-B", "-u", GAME]
        if WINDOWS:
            from winpty import PtyProcess
            self.child = PtyProcess.spawn(argv, env=self.env, dimensions=(24, 80))
            read = self.child.read
            self.send = self.child.write
        else:
            import fcntl
            import pty
            import struct
            import subprocess
            import termios
            self.master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            self.child = subprocess.Popen(argv, env=self.env, stdin=slave, stdout=slave, stderr=slave)
            os.close(slave)
            decode = codecs.getincrementaldecoder("utf-8")("replace")
            read = lambda: decode.decode(os.read(self.master, 65536))
            self.send = lambda text: os.write(self.master, text.encode("utf-8"))

        def collect():
            try:
                while True:
                    data = read()
                    if data:
                        self.output.put(data)
            except (EOFError, OSError):
                self.output.put(None)

        Thread(target=collect, daemon=True).start()
        return self

    def __exit__(self, *_):
        if WINDOWS:
            self.child.close(force=True)
        else:
            if self.child.poll() is None:
                self.child.kill()
            self.child.wait()
            os.close(self.master)

    def size(self, rows, cols):
        if WINDOWS:
            self.child.setwinsize(rows, cols)
        else:
            import fcntl
            import struct
            import termios
            fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        self.screen.resize(rows, cols)

    def wait(self, *markers, changed=None):
        deadline = monotonic() + 12
        while True:
            lines = tuple(self.screen.display)
            if all(any(marker in line for line in lines) for marker in markers):
                if changed is None or self.map() != changed:
                    return
            try:
                data = self.output.get(timeout=max(0.001, deadline - monotonic()))
            except Empty:
                break
            if data is None or monotonic() > deadline:
                break
            self.stream.feed(data)
        raise AssertionError(f"Waiting for {markers}\n" + "\n".join(self.screen.display))

    def text(self, value):
        self.send(value + ENTER)

    def map(self):
        # The first two rows are the title and objective. Map cells start at x=0.
        height = 18 if self.screen.display[0].startswith("L2 - MAIN DECK") else 12
        return tuple(line[:60] for line in self.screen.display[2:2+height])

    def walk(self, path):
        for key in path:
            before = self.map()
            self.send(key)
            self.wait(PROMPT, changed=before)

    def reject(self, command, feedback):
        before = self.map()
        self.send(command)
        self.wait(PROMPT, feedback)
        assert self.map() == before, "Rejected action changed map or enemy position"

    def mode(self, mode):
        self.wait("DEBUG MENU")
        self.text(mode)


def forest():
    with Game() as game:
        game.mode("forest")
        game.wait("Press Enter to enter the forest >", f"You are {ICON}")
        game.text("")
        game.wait(PROMPT, "Flash: 100%", "Goal: Reach >")
        assert game.map()[1][1:3] == ICON + " "
        game.reject("w", "Dense undergrowth blocks that path.")
        game.reject("k", "Unknown command.")
        game.reject("e", "Get closer to the shop")
        game.send("f")
        game.wait("Aim [WASD")
        game.reject("k", "Use W, A, S, or D to aim the flash.")
        if not WINDOWS:
            game.reject("\x1b[200~" + "wasdftex\n" * 100 + "\x1b[201~", "Pasted text was ignored.")
        before = game.map()
        game.size(23, 79)
        game.send("d")
        game.wait("Resize to 80 x 24 to continue.")
        game.size(24, 80)
        game.wait("Continue >")
        game.text("")
        game.wait(PROMPT, "Flash: 100%")
        assert game.map() == before
        game.walk("d")
        game.wait("Flash: 99%")
        assert game.map()[1][2] == ICON
        game.send("x")
    print("PASS forest briefing, icon alignment, rejected actions, resize and direct WASD")


def puzzle(game, room, wrong, correct):
    game.send("e")
    game.wait(room, "Setting >")
    game.text(correct + " " * 40 + "junk")
    game.wait("Enter three digits, or X to close the panel.", "Setting >")
    game.text(wrong)
    game.wait("Hint 1/4:", "Setting >")
    game.text(correct)
    game.wait("Correct!", "Press Enter to return to the map >")
    game.text("")
    game.wait(PROMPT)


def deck_route(start, door_row):
    tree = ast.parse(Path(GAME).read_bytes())
    grid = ast.literal_eval(next(node.value for node in tree.body
                               if isinstance(node, ast.Assign)
                               and isinstance(node.targets[0], ast.Name)
                               and node.targets[0].id == "ship_map"
                               and isinstance(node.value, ast.List)))
    goal = (grid[door_row].index("E"), door_row)
    queue = deque([(start, "")])
    visited = {start}
    while queue:
        (x, y), route = queue.popleft()
        if (x, y) == goal:
            return route
        for dx, dy, key in ((1, 0, "d"), (-1, 0, "a"), (0, 1, "s"), (0, -1, "w")):
            nx, ny = x + dx, y + dy
            if not (0 <= ny < len(grid) and 0 <= nx < len(grid[ny])):
                continue
            if (nx, ny) not in visited and (grid[ny][nx] in ".@" or (nx, ny) == goal):
                visited.add((nx, ny))
                queue.append(((nx, ny), route + key))
    raise AssertionError("Engine door is unreachable")


def ship():
    with Game() as game:
        game.mode("ship")
        game.wait("Press Enter to board your ship >")
        game.text("")
        game.wait(PROMPT, "L2 - MAIN DECK", "Goal: Enter the upper engine")
        assert "[1]" in game.map()[0] and "[2]" in game.map()[-1]
        assert game.map()[11][14] == ICON
        # Reach the upper console, keeping one tile of separation.
        game.walk(deck_route((14, 11), 0) + "w" * 4)
        game.wait("UPPER ENGINE ROOM", "Goal: Stand next to C")
        puzzle(game, "UPPER ENGINE | CONNECT THE PARTS", "123", "231")
        game.wait("Upper: ON | Lower: OFF")
        game.walk("s" * 5)
        game.wait("Goal: Enter the lower engine")
        game.walk(deck_route((24, 1), 17) + "s" * 4)
        game.wait("LOWER ENGINE ROOM", "Goal: Stand next to C")
        puzzle(game, "LOWER ENGINE | BALANCE THE FUEL", "123", "342")
        game.wait("Upper: ON | Lower: ON", "The Ghost and Hunter are here!")
        game.walk("w" * 5)
        game.wait("Goal: Reach the reactor room")
        game.reject("e", "Nothing to use here.")
        game.reject("k", "Unknown command.")
        game.send("x")
    print("PASS ship doors, both linked repairs, invalid answer recovery and active-enemy state")


if __name__ == "__main__":
    print(sys.platform, sys.version.split()[0], "80 x 24")
    forest()
    ship()
