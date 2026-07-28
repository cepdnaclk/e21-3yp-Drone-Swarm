import os
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "Drone-swarm-v1" / "computer_code" / "api"
FRONTEND_DIR = REPO_ROOT / "Drone-swarm-v1" / "computer_code" / "src"

if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from runtime_paths import ensure_runtime_data  # noqa: E402


class DeploymentRuntimeTests(unittest.TestCase):
    def test_runtime_data_is_seeded_and_user_changes_are_preserved(self):
        old_override = os.environ.get("DRONE_SWARM_DATA_DIR")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.environ["DRONE_SWARM_DATA_DIR"] = temp_dir
                paths = ensure_runtime_data()

                self.assertEqual(paths.data_dir, Path(temp_dir).resolve())
                self.assertTrue(paths.fleet_file.is_file())
                self.assertTrue(paths.settings_file.is_file())
                self.assertTrue(paths.uploads_dir.is_dir())
                self.assertTrue(paths.logs_dir.is_dir())
                self.assertTrue(
                    (paths.calibration_dir / "camera_1_params_new.json").is_file()
                )

                paths.settings_file.write_text('{"custom": true}', encoding="utf-8")
                ensure_runtime_data()
                self.assertEqual(
                    paths.settings_file.read_text(encoding="utf-8"),
                    '{"custom": true}',
                )
        finally:
            if old_override is None:
                os.environ.pop("DRONE_SWARM_DATA_DIR", None)
            else:
                os.environ["DRONE_SWARM_DATA_DIR"] = old_override

    def test_frontend_source_has_no_fixed_backend_origin(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in FRONTEND_DIR.rglob("*")
            if path.suffix in {".ts", ".tsx"}
        )
        self.assertNotIn("http://localhost:3001", source)
        self.assertNotIn("http://127.0.0.1:3001", source)
        self.assertIn("window.location.origin", source)


if __name__ == "__main__":
    unittest.main()
