"""
PM2 process manager for dynamic watcher spawning/killing.
"""
import subprocess


def spawn_watcher(user_id: int) -> bool:
    name = f"iqbot-v2-watcher-{user_id}"
    cmd = [
        "pm2", "start", "main_watcher.py",
        "--name", name,
        "--interpreter", "python3",
        "--", str(user_id)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return result.returncode == 0


def kill_watcher(user_id: int) -> bool:
    name = f"iqbot-v2-watcher-{user_id}"
    result = subprocess.run(["pm2", "delete", name], capture_output=True, timeout=10)
    return result.returncode == 0


def watcher_status(user_id: int) -> str:
    name = f"iqbot-v2-watcher-{user_id}"
    result = subprocess.run(
        ["pm2", "describe", name, "--format", "json"],
        capture_output=True, text=True, timeout=10
    )
    if "online" in result.stdout:
        return "ONLINE"
    elif "stopped" in result.stdout:
        return "STOPPED"
    return "UNKNOWN"
