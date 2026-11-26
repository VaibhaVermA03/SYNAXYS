
"""Run the SYNAXYS API and background worker in one Render web service."""
import os
import signal
import subprocess
import sys
import threading
import time

stop_event = threading.Event()
processes = []


def handle_signal(signum, frame):
    stop_event.set()


def main():
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Render supplies PORT as an environment variable.
    # Validate it before passing it to Uvicorn.
    port = int(os.environ.get("PORT", "10000"))

    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")

    api_command = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--proxy-headers",
    ]

    api_env = os.environ.copy()
    api_env["UVICORN_PORT"] = str(port)

    worker_command = [
        sys.executable, "-m", "app.workers.runner",
    ]

    exit_code = 0

    try:
        worker = subprocess.Popen(worker_command)
        processes.append(worker)
        print("SYNAXYS worker started.", flush=True)

        api = subprocess.Popen(api_command, env=api_env)
        processes.append(api)
        print("SYNAXYS API started.", flush=True)

        while not stop_event.wait(1):
            for name, process in [
                ("worker", worker),
                ("api", api),
            ]:
                code = process.poll()

                if code is not None:
                    print(
                        f"{name} exited unexpectedly: {code}",
                        flush=True,
                    )
                    exit_code = 1
                    stop_event.set()
                    break

    finally:
        print("Stopping API and worker...", flush=True)

        for process in processes:
            if process.poll() is None:
                process.terminate()

        deadline = time.monotonic() + 22

        for process in processes:
            if process.poll() is None:
                remaining = max(0, deadline - time.monotonic())

                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

        print("SYNAXYS processes stopped.", flush=True)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
