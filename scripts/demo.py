"""One command for the demo: the database, the API and the web app, ready to sign in.

    .venv/bin/python scripts/demo.py               # the web app as a production build (about a minute to build)
    .venv/bin/python scripts/demo.py --dev         # `next dev` instead: starts at once, compiles pages on first visit
    .venv/bin/python scripts/demo.py --reset       # first rebuild the dev database from sql/ (scripts/reset_db.py)
    .venv/bin/python scripts/demo.py --api-port 8004 --web-port 3004     # a worktree's own ports

(Windows: .venv\\Scripts\\python scripts\\demo.py …) Ctrl-C stops the API and the web app; the database keeps
running. Logs go to .demo/. Sign-in is Clerk's hosted service, so the demo needs the internet.

The database container belongs to the main checkout: there this starts it (`docker compose up -d db`) if it isn't
running; in a worktree it never runs docker compose, and asks you to start it from the main checkout instead.
"""
import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
LOGS = ROOT / ".demo"
PERSONAS = [
    ("Alice Morgan", "customer", "alice.morgan+clerk_test@example.com"),
    ("Aiden Chen", "store staff, Sydney CBD", "aiden.chen+clerk_test@example.com"),
    ("Olivia Nguyen", "manager, Sydney CBD", "olivia.nguyen+clerk_test@example.com"),
    ("Nora Fitzgerald", "support", "nora.fitzgerald+clerk_test@example.com"),
]


def missing_web_origin(parties: str | None, web_port: int) -> str | None:
    """The origin the API's AUTH_AUTHORIZED_PARTIES lacks for this web port (sign-in would be refused), or None."""
    origin = f"http://localhost:{web_port}"
    return None if origin in (parties or "").split(",") else origin


def in_worktree() -> bool:
    """True in a linked git worktree: its git dir differs from the common one (the main checkout's .git)."""
    def git_path(flag: str) -> Path:
        out = subprocess.run(["git", "rev-parse", flag], cwd=ROOT, capture_output=True, text=True, check=True)
        return (ROOT / out.stdout.strip()).resolve()
    return git_path("--git-dir") != git_path("--git-common-dir")


def say(text: str) -> None:
    print(text, flush=True)


def fail(text: str) -> int:
    print(text, file=sys.stderr, flush=True)
    return 1


def database_up() -> bool:
    try:
        psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"], dbname="postgres",
                         user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
                         connect_timeout=3).close()
        return True
    except psycopg2.OperationalError:
        return False


def database_exists(dbname: str) -> bool:
    try:
        psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"], dbname=dbname,
                         user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
                         connect_timeout=3).close()
        return True
    except psycopg2.OperationalError:
        return False


def port_in_use(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def start(name: str, command: list[str], env: dict | None = None) -> subprocess.Popen:
    """Start a long-running process in its own process group, its output in .demo/<name>.log."""
    log = open(LOGS / f"{name}.log", "w")
    options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
               else {"start_new_session": True})
    return subprocess.Popen(command, cwd=ROOT if name == "api" else WEB, env=env, stdout=log,
                            stderr=subprocess.STDOUT, **options)


def stop(process: subprocess.Popen) -> None:
    """Stop a process and everything it started (npx → next → its server), then wait for it."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def answers(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status == 200
    except OSError:
        return False


def tail(name: str, lines: int = 15) -> str:
    text = (LOGS / f"{name}.log").read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(text[-lines:])


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the database, the API and the web app for the demo.")
    parser.add_argument("--dev", action="store_true", help="run `next dev` instead of a production build")
    parser.add_argument("--reset", action="store_true", help="rebuild the dev database from sql/ first")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=3000)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    # ---- what has to be there before anything starts
    if not (ROOT / ".env").exists():
        return fail("No .env: copy .env.example to .env and fill in the Clerk lines (README → Sign-in).")
    if not (WEB / ".env.local").exists():
        return fail("No web/.env.local: copy web/.env.example and fill in the Clerk keys (README → Sign-in).")
    npm, npx = shutil.which("npm"), shutil.which("npx")
    if not npm or not npx:
        return fail("Node.js isn't installed (npm and npx are needed for the web app).")
    if not (WEB / "node_modules").exists():
        return fail("The web app's packages aren't installed: run `cd web && npm install` once.")
    origin = missing_web_origin(os.environ.get("AUTH_AUTHORIZED_PARTIES"), args.web_port)
    if origin:
        say(f"Warning: AUTH_AUTHORIZED_PARTIES in .env doesn't list {origin}, so the API will refuse sign-ins "
            "from this web port.")
    for port in (args.api_port, args.web_port):
        if port_in_use(port):
            return fail(f"Port {port} is already in use: stop whatever runs there, or choose another port.")
    LOGS.mkdir(exist_ok=True)

    # ---- the database
    if not database_up():
        if in_worktree():
            return fail("The database isn't running. Start it from the main checkout (`docker compose up -d`); "
                        "a worktree never runs docker compose.")
        say("Starting the database (docker compose up -d db)…")
        subprocess.run(["docker", "compose", "up", "-d", "db"], cwd=ROOT, check=True)
        for _ in range(60):
            if database_up():
                break
            time.sleep(1)
        else:
            return fail("The database didn't come up within a minute: see `docker compose logs db`.")
    dbname = os.environ["POSTGRES_DB"]
    if args.reset:
        sys.path.insert(0, str(ROOT / "scripts"))
        import reset_db
        if reset_db.main() != 0:
            return fail("The reset didn't finish (above); not starting the demo.")
    elif not database_exists(dbname):
        return fail(f"The database {dbname} doesn't exist yet: run again with --reset to build it from sql/.")

    # ---- the API and the web app
    processes: list[subprocess.Popen] = []
    try:
        say(f"Starting the API on port {args.api_port}…")
        processes.append(start("api", [sys.executable, "-m", "fastapi", "run", "app/main.py",
                                       "--host", "127.0.0.1", "--port", str(args.api_port)]))
        # Next.js forwards /api/* to the API (web/next.config.ts). A production build fixes that address when it
        # is built, so it is built with this run's port.
        web_env = {**os.environ, "API_URL": f"http://127.0.0.1:{args.api_port}"}
        if args.dev:
            processes.append(start("web", [npx, "next", "dev", "-p", str(args.web_port)], web_env))
        else:
            say("Building the web app (next build — about a minute; log: .demo/web-build.log)…")
            with open(LOGS / "web-build.log", "w") as log:
                built = subprocess.run([npm, "run", "build"], cwd=WEB, env=web_env, stdout=log,
                                       stderr=subprocess.STDOUT)
            if built.returncode != 0:
                return fail("The web app didn't build:\n" + tail("web-build"))
            processes.append(start("web", [npx, "next", "start", "-p", str(args.web_port)], web_env))

        say("Waiting for the API and the web app to answer…")
        checks = {"API": f"http://127.0.0.1:{args.api_port}/health",
                  "web app → API": f"http://127.0.0.1:{args.web_port}/api/health"}
        deadline = time.monotonic() + 120
        while not all(answers(url) for url in checks.values()):
            for name, process in zip(("api", "web"), processes):
                if process.poll() is not None:
                    return fail(f"The {name} process stopped:\n" + tail(name))
            if time.monotonic() > deadline:
                return fail("Still not answering after two minutes. Logs: .demo/api.log, .demo/web.log")
            time.sleep(1)
        for name, url in checks.items():
            say(f"  ok  {name}: {url}")

        say(f"""
Ready. Database {dbname} · API on {args.api_port} · web app on {args.web_port}{" (dev)" if args.dev else ""}
  Storefront   http://localhost:{args.web_port}
  Store admin  http://localhost:{args.web_port}/admin
  API docs     http://127.0.0.1:{args.api_port}/docs
Sign in with one of these (the password set with scripts/clerk_personas.py; an email code is 424242):""")
        for name, role, email in PERSONAS:
            say(f"  {name:<16} {role:<26} {email}")
        say("Ctrl-C stops the API and the web app (the database keeps running). Logs: .demo/")

        while all(process.poll() is None for process in processes):
            time.sleep(1)
        stopped = next(name for name, process in zip(("api", "web"), processes) if process.poll() is not None)
        return fail(f"The {stopped} process stopped:\n" + tail(stopped))
    except KeyboardInterrupt:
        say("\nStopping…")
        return 0
    finally:
        for process in reversed(processes):
            stop(process)
        if processes:
            say("The API and the web app are stopped; the database is still running.")


if __name__ == "__main__":
    sys.exit(main())
