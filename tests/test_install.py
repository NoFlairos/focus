"""Exercise native-host registration without touching the user's installation."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install-browser-host.sh"
EXTENSION_ID = "a" * 32


class HostInstallTests(unittest.TestCase):
    def test_registration_requires_helper_and_preserves_paths(self):
        with tempfile.TemporaryDirectory(prefix="focus-host-") as temporary:
            root = Path(temporary)
            data = root / 'data with "quotes"'
            config = root / "config"
            environment = dict(os.environ, XDG_DATA_HOME=str(data), XDG_CONFIG_HOME=str(config))

            def register(extension_id=EXTENSION_ID):
                return subprocess.run(["bash", str(SCRIPT), extension_id], env=environment,
                                      capture_output=True, text=True, check=False)

            self.assertEqual(register().returncode, 1)
            self.assertFalse(config.exists())
            helper = data / "focus-ratio/focus_ratio_agent.py"
            helper.parent.mkdir(parents=True)
            helper.write_text("#!/usr/bin/env python3\n")
            helper.chmod(0o755)
            self.assertEqual(register("invalid-id").returncode, 2)
            result = register()
            self.assertEqual(result.returncode, 0, result.stderr)
            for browser in ("chromium", "google-chrome"):
                path = config / browser / "NativeMessagingHosts/io.github.noflairos.focus_ratio.json"
                manifest = json.loads(path.read_text())
                self.assertEqual(manifest["path"], str(helper.parent / "native-host.sh"))
                self.assertEqual(manifest["allowed_origins"], [f"chrome-extension://{EXTENSION_ID}/"])
                self.assertTrue(os.access(manifest["path"], os.X_OK))
