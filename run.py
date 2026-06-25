"""A机/B机统一入口。sender pull→下单→push，receiver pull→下单，不push。"""

import subprocess
import sys
from pathlib import Path

import userConfig

THIS_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable
GIT = ["git"]
PULL = GIT + ["fetch", "--all"]
RESET = GIT + ["reset", "--hard", "origin/main"]


def git_pull():
    for cmd in (PULL, RESET):
        completed = subprocess.run(cmd, cwd=str(THIS_DIR), text=True, capture_output=True)
        if completed.returncode != 0:
            print(f"run.py: git error ({cmd[1]}): {completed.stderr.strip()}", flush=True)
            return False
    print("run.py: git sync done", flush=True)
    return True


def run_main():
    completed = subprocess.run([PYTHON, "main.py"], cwd=str(THIS_DIR))
    return completed.returncode == 0


def run_push():
    completed = subprocess.run([PYTHON, "push.py"], cwd=str(THIS_DIR))
    return completed.returncode == 0


def main():
    role = userConfig.role

    if role == "receiver" and not git_pull():
        return 1

    if not run_main():
        print("run.py: main.py failed", flush=True)
        return 1

    if role == "sender" and not run_push():
        print("run.py: push.py failed", flush=True)
        return 1

    print(f"run.py: {role} done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
