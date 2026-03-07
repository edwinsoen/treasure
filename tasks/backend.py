"""Backend development tasks."""

import time

from invoke import Context, task

_MONGO_CONTAINER = "treasure-test-mongo"
_MONGO_PORT = 27018
_MONGO_DB = "treasure_invoke_test"
_MONGO_URI = f"mongodb://localhost:{_MONGO_PORT}/{_MONGO_DB}"


def _ensure_container(
    ctx: Context, name: str, port: int, image: str = "mongo:7"
) -> None:
    """Start a Docker container if not already running."""
    result = ctx.run(
        f"docker inspect -f '{{{{.State.Running}}}}' {name}",
        hide=True,
        warn=True,
    )
    if result and result.ok and result.stdout.strip() == "true":
        return

    # Container exists but stopped?
    exists = ctx.run(f"docker inspect {name}", hide=True, warn=True)
    if exists and exists.ok:
        print(f"Starting stopped container {name}...")
        ctx.run(f"docker start {name}", hide=True)
    else:
        print(f"Creating container {name} (port {port})...")
        ctx.run(
            f"docker run -d --name {name} -p {port}:27017 {image}",
            hide=True,
        )

    # Wait for ready
    for _ in range(20):
        ping = ctx.run(
            f"docker exec {name} "
            "mongosh --quiet --eval \"db.runCommand('ping').ok\"",
            hide=True,
            warn=True,
        )
        if ping and ping.ok and ping.stdout.strip() == "1":
            print("MongoDB ready.")
            return
        time.sleep(0.5)

    raise RuntimeError("MongoDB did not become ready within 10 seconds.")


@task(positional=["args"])
def test(ctx: Context, args: str = "") -> None:
    """Run backend tests. Starts MongoDB automatically.

    Examples:
        invoke test
        invoke test test_accounts.py
        invoke test test_accounts.py::TestPatchAccount
        invoke test -- -k test_replace
    """
    _ensure_container(ctx, _MONGO_CONTAINER, _MONGO_PORT)

    pytest_args = args
    if pytest_args and not pytest_args.startswith("-"):
        pytest_args = f"tests/{pytest_args}"

    cmd = f"cd backend && uv run pytest -v {pytest_args}".strip()
    ctx.run(cmd, env={"TSR_MONGODB_URI": _MONGO_URI}, pty=True)


@task(name="test-stop")
def test_stop(ctx: Context) -> None:
    """Stop and remove the test MongoDB container."""
    ctx.run(f"docker rm -f {_MONGO_CONTAINER}", warn=True)
    print(f"Removed {_MONGO_CONTAINER}.")


