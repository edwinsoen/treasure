"""Project task namespace."""

from invoke import Collection

from tasks import backend, stack

ns = Collection()
ns.add_task(backend.test)
ns.add_task(backend.test_stop, name="test-stop")
ns.add_task(stack.start)
ns.add_task(stack.stop)
ns.add_task(stack.start_dev, name="start-dev")
ns.add_task(stack.stop_dev, name="stop-dev")
