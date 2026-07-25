import ast
import unittest
from pathlib import Path


API_INDEX = Path(__file__).resolve().parents[2] / "Drone-swarm-v1" / "computer_code" / "api" / "index.py"


class AlgorithmUploadSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = API_INDEX.read_text(encoding="utf-8")
        module = ast.parse(source)
        namespace = {"ast": ast, "ValueError": ValueError}

        needed = {
            "AlgorithmValidationError",
            "AlgorithmSourceValidator",
            "validate_algorithm_source",
        }
        for node in module.body:
            names = set()
            if isinstance(node, ast.Assign):
                names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            elif isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                names = {node.name}
            if names & needed:
                exec(compile(ast.Module([node], []), str(API_INDEX), "exec"), namespace)

        cls.validate_algorithm_source = staticmethod(namespace["validate_algorithm_source"])
        cls.AlgorithmValidationError = namespace["AlgorithmValidationError"]
        cls.source = source
        cls.tree = module
        cls.allowed_calls = {
            "arm", "disarm", "takeoff", "land",
            "goto", "move", "set_yaw", "wait",
            "get_position", "get_battery", "list_active", "get_state",
            "log", "print",
        }

    def test_safe_mission_script_is_allowed(self):
        tree = self.validate_algorithm_source(
            """
log("mission starting")
log("state", get_state())
goto(0.0, 0.0, 0.25)
wait(1)
land()
""",
            self.allowed_calls,
        )

        self.assertIsInstance(tree, ast.Module)

    def test_allowed_calls_are_supplied_by_api_keys(self):
        tree = self.validate_algorithm_source("new_safe_command(1)", {"new_safe_command"})

        self.assertIsInstance(tree, ast.Module)

    def test_imports_attributes_and_unknown_calls_are_rejected(self):
        malicious_examples = [
            "import os\nlog('bad')",
            "__import__('os').system('dir')",
            "open('settings.json').read()",
            "log.__globals__",
            "exec('print(1)')",
            "x = 1",
            "for i in [1]:\n    log(i)",
        ]

        for source in malicious_examples:
            with self.subTest(source=source):
                with self.assertRaises(self.AlgorithmValidationError):
                    self.validate_algorithm_source(source, self.allowed_calls)

    def test_upload_handler_validates_before_starting_runner(self):
        handler = next(
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef) and node.name == "on_algorithm_upload"
        )
        runner_class = next(
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.ClassDef) and node.name == "AlgorithmRunner"
        )
        start_method = next(
            node for node in runner_class.body
            if isinstance(node, ast.FunctionDef) and node.name == "start"
        )

        self.assertIn("_algorithm_runner.start", ast.unparse(handler))
        start_source = ast.unparse(start_method)
        self.assertIn("api = self._build_api()", start_source)
        self.assertIn("validate_algorithm_source(source, api.keys())", start_source)
        self.assertIn('"__builtins__": {}', self.source)


if __name__ == "__main__":
    unittest.main()
