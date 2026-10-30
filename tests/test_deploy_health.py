"""Recovery must not turn normal maintenance stops into unwanted restarts."""
import os
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/check-health.sh"


@pytest.mark.parametrize("service", ["app", "phone"])
@pytest.mark.parametrize("state,expected", [("healthy", False), ("starting", False),
                                           ("stopped", False), ("unhealthy", True)])
def test_health_recovery_only_for_unhealthy_running_app(tmp_path, state, expected, service):
    docker = tmp_path / "docker"
    docker.write_text('''#!/bin/sh
case "$*" in
  *"ps -q $TEST_SERVICE") [ "$TEST_STATE" = stopped ] || echo synthetic-container ;;
  *"ps -q "*) : ;;
  inspect*) echo "$TEST_STATE" ;;
  *"restart $TEST_SERVICE") echo restarted > "$TEST_MARKER" ;;
  *) exit 2 ;;
esac
exit 0
''')
    docker.chmod(0o755)
    marker = tmp_path / "restart"
    env = {**os.environ, "PATH": str(tmp_path) + ":" + os.environ["PATH"],
           "TEST_STATE": state, "TEST_MARKER": str(marker), "TEST_SERVICE": service}
    subprocess.run(["sh", str(SCRIPT)], env=env, check=True, capture_output=True)
    assert marker.exists() is expected
