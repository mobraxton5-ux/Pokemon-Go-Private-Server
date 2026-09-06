"""
Where the server keeps everything it writes: a `data` folder beside the .exe.

Everything used to be dumped straight next to the executable -- settings.json,
every save, the gyms, the log, the photos folder -- so the release folder was a
pile of files with the thing you actually double-click buried among them. It all
lives in `data/` now, and this module is the single place that knows that. Five
different modules each had their own copy of this logic before; they all call in
here instead.

Anything an older build left beside the .exe is moved in on first run, so an
existing collection carries over untouched.
"""
import os
import shutil
import sys

# Files and folders older builds wrote beside the .exe. Order doesn't matter;
# each is moved only if `data/` doesn't already have its own copy.
LEGACY = ("settings.json", "places.json", "events.json", "gyms.json",
          "lures.json", "raid.json", "save.json", "nominations.json",
          "server-log.txt", "saves", "photos")


def base_dir():
    """The folder the user sees: the .exe's folder, or the source folder."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DATA_DIR = os.path.join(base_dir(), "data")


def path(*parts):
    """A path inside data/, with the folder guaranteed to exist."""
    ensure()
    return os.path.join(DATA_DIR, *parts)


_ready = False


def ensure():
    global _ready
    if _ready:
        return DATA_DIR
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        _migrate()
    except OSError:
        pass
    _ready = True
    return DATA_DIR


def _migrate():
    """Move an older layout's files into data/. Never overwrites: if both exist,
    the copy already in data/ wins and the stray one is left alone rather than
    silently thrown away -- one of them is somebody's save file."""
    moved = []
    for name in LEGACY:
        old = os.path.join(base_dir(), name)
        new = os.path.join(DATA_DIR, name)
        if not os.path.exists(old) or os.path.exists(new):
            continue
        try:
            shutil.move(old, new)
            moved.append(name)
        except (OSError, shutil.Error):
            pass
    if moved:
        # print, not log: this runs before logging is set up
        print(f"[data] moved into data/: {', '.join(moved)}", flush=True)
    return moved
