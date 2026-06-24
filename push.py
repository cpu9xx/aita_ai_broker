"""Push to GitHub. Sender pushes code+JSON, receiver also pushes reports."""

import datetime as dt
import subprocess
from pathlib import Path

import userConfig

THIS_DIR = Path(__file__).resolve().parent


def main():
    message = f"auto: order json {dt.date.today().strftime('%Y%m%d')}"
    print(f"push.py: {message}", flush=True)

    git_cmds = [["git", "add", "-A"]]

    if userConfig.role == "receiver":
        reports_dir = userConfig.report_output_dir
        if Path(reports_dir).exists():
            git_cmds.append(["git", "add", "-f", str(reports_dir)])

    git_cmds += [
        ["git", "commit", "-m", message],
        ["git", "push"],
    ]

    for cmd in git_cmds:
        completed = subprocess.run(cmd, cwd=str(THIS_DIR), text=True, capture_output=True)
        if completed.returncode != 0:
            if cmd[1] == "commit" and "nothing to commit" in completed.stdout:
                print("push.py: nothing to commit", flush=True)
                return 0
            print(f"push.py error: {completed.stderr.strip()}", flush=True)
            return 1

    print("push.py: done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
