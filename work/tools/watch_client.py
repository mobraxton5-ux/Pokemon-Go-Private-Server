"""
Watch the Pokemon GO client on the phone over adb and report whether it is
BUSY (grinding through the game master) or IDLE (genuinely hung).

The release client strips its own logs, so this is our only window into what it's
doing. Reads /proc/<pid>/stat fields 14/15 (utime/stime, in clock ticks) and
reports the CPU delta per sample.

  BUSY  -> it's applying the game master; leave it alone, it will finish + reboot.
  IDLE  -> it's waiting on something (us) or deadlocked; restarting won't help.

Usage:  py work/tools/watch_client.py [seconds_between_samples] [samples]
"""
import os
import subprocess
import sys
import time

ADB = os.environ.get(
    "ADB", r"C:\Users\mobra\AppData\Local\Android\Sdk\platform-tools\adb.exe")
PKG = "com.nianticlabs.pokemongo"


def sh(*args):
    try:
        return subprocess.run([ADB] + list(args), capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except Exception as e:
        return f"ERR {e}"


def pid_of():
    out = sh("shell", "pidof", PKG).split()
    return out[0] if out else None


def cpu_ticks(pid):
    """utime+stime for the process (fields 14,15, 1-indexed) in clock ticks."""
    raw = sh("shell", "cat", f"/proc/{pid}/stat")
    if not raw or raw.startswith("ERR"):
        return None
    # comm can contain spaces/parens -> split after the closing paren
    tail = raw[raw.rfind(")") + 1:].split()
    try:
        return int(tail[11]) + int(tail[12])       # utime, stime
    except (IndexError, ValueError):
        return None


def main():
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    samples = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    devs = sh("devices")
    print(devs)
    if "unauthorized" in devs:
        print("\n!! Phone shows 'unauthorized' -- tap ALLOW on the 'Allow USB "
              "debugging?' popup on the phone screen, then re-run.")
        return 1
    if "\tdevice" not in devs:
        print("\n!! No authorized device. Plug in via USB + enable USB debugging.")
        return 1

    pid = pid_of()
    if not pid:
        print(f"\n{PKG} is not running -- start the game first.")
        return 1
    print(f"\nwatching pid {pid}  ({interval}s x {samples})\n")

    HZ = 100.0                       # Android clock ticks per second
    prev = cpu_ticks(pid)
    busy = idle = 0
    for i in range(samples):
        time.sleep(interval)
        now = cpu_ticks(pid)
        if now is None or prev is None:
            print("  (process gone -- it restarted? that's the SUCCESS signal)")
            return 0
        pct = (now - prev) / HZ / interval * 100.0
        state = "BUSY  <- working" if pct > 8 else "idle  <- waiting/hung"
        print(f"  [{i+1:2}] cpu {pct:5.1f}%   {state}")
        busy += pct > 8
        idle += pct <= 8
        prev = now
        if pid_of() != pid:
            print("\n  ** process restarted -- game master applied successfully! **")
            return 0

    print(f"\nsummary: {busy} busy / {idle} idle samples")
    print("  mostly BUSY -> it IS working; give it more time, do not restart.")
    print("  mostly idle -> it is NOT working; it's stuck waiting, not computing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
