"""Docker Compose stack tasks.

invoke start       — prod-like stack (all services in Docker, :8080)
invoke stop        — stop prod-like stack
invoke start-dev   — dev stack (Docker backend + Vite frontend with HMR)
invoke stop-dev    — stop dev stack
"""

import signal

from invoke import Context, task

_COMPOSE_DIR = "docker"
_COMPOSE_BASE = f"{_COMPOSE_DIR}/docker-compose.yml"
_COMPOSE_DEV = f"{_COMPOSE_DIR}/docker-compose.dev.yml"


@task
def start(ctx: Context) -> None:
    """Start all services in Docker (prod-like). App on :8080."""
    ctx.run(
        f"docker compose --env-file .env -f {_COMPOSE_BASE} up --build -d",
        pty=True,
    )
    print("Stack running at http://localhost:8080")


@task
def stop(ctx: Context) -> None:
    """Stop the prod-like stack."""
    ctx.run(f"docker compose -f {_COMPOSE_BASE} down", pty=True)


@task(name="start.dev")
def start_dev(ctx: Context) -> None:
    """Start dev stack: Docker (backend :8000 + MongoDB :27017) and Vite (:5173)."""
    ctx.run(
        f"docker compose --env-file .env "
        f"-f {_COMPOSE_BASE} -f {_COMPOSE_DEV} up --build -d",
        pty=True,
    )
    print("Backend on :8000, MongoDB on :27017.")
    print("Starting frontend (Vite) on :5173... Ctrl+C to stop all.\n")

    try:
        ctx.run("cd frontend && npm run dev", pty=True)
    except (KeyboardInterrupt, signal.Signals):
        pass
    finally:
        print("\nStopping Docker services...")
        ctx.run(
            f"docker compose -f {_COMPOSE_BASE} -f {_COMPOSE_DEV} down",
            pty=True,
        )


@task(name="stop.dev")
def stop_dev(ctx: Context) -> None:
    """Stop the dev stack."""
    ctx.run(
        f"docker compose -f {_COMPOSE_BASE} -f {_COMPOSE_DEV} down",
        pty=True,
    )
