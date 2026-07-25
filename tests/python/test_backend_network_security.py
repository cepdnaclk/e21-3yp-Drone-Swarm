import ast
import unittest
from pathlib import Path


API_INDEX = Path(__file__).resolve().parents[2] / "Drone-swarm-v1" / "computer_code" / "api" / "index.py"


class BackendNetworkSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = API_INDEX.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_backend_host_defaults_to_localhost(self):
        assignment = next(
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "BACKEND_HOST" for target in node.targets)
        )

        source = ast.unparse(assignment)
        self.assertIn("DRONE_BACKEND_HOST", source)
        self.assertIn("'127.0.0.1'", source)

    def test_socketio_run_uses_configured_backend_host(self):
        run_call = next(
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "socketio"
        )
        keyword_values = {keyword.arg: ast.unparse(keyword.value) for keyword in run_call.keywords}

        self.assertEqual(keyword_values["host"], "BACKEND_HOST")
        self.assertNotIn('host="0.0.0.0"', self.source)
        self.assertNotIn("host='0.0.0.0'", self.source)


if __name__ == "__main__":
    unittest.main()
