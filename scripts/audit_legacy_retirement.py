"""Report tracked legacy source candidates without deleting files or opening databases.

This is migration evidence, not a second runtime interface. Run from a Git checkout;
its output records the exact source commit and installed-package configuration.
"""

from __future__ import annotations

import ast
import json
import subprocess
import tomllib
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root, text=True).split("\0")[
        :-1
    ]
    config = tomllib.loads((root / "pyproject.toml").read_text())
    prefixes = (
        "agent_vis/",
        "frontend/",
        "tests/test_",
        "tests/perf/",
        "skills/chat_trajectory/",
    )
    exact = {
        "Cargo.toml",
        "src/lib.rs",
        "install.sh",
        "uninstall.sh",
        "tests/conftest.py",
        "scripts/export_openapi_schema.py",
        "scripts/profile_real_sync.py",
        "scripts/run_backend_perf.py",
        "scripts/run_parser_bench.py",
        ".github/workflows/backend-performance.yml",
        ".github/workflows/nightly-frontend.yml",
    }
    candidates = sorted(path for path in tracked if path.startswith(prefixes) or path in exact)
    imports: dict[str, list[str]] = {}
    for path in sorted((root / "trajectory").rglob("*.py")):
        modules: set[str] = set()
        for item in ast.walk(ast.parse(path.read_text())):
            if isinstance(item, ast.ImportFrom) and not item.level:
                modules.add(item.module or "")
            elif isinstance(item, ast.Import):
                modules.update(alias.name for alias in item.names)
        imports[str(path.relative_to(root))] = sorted(modules)
    references = []
    for path, modules in imports.items():
        for module in modules:
            if module == "agent_vis" or module.startswith("agent_vis."):
                references.append({"path": path, "module": module})
    result = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "project_scripts": config["project"]["scripts"],
        "package_include": config["tool"]["setuptools"]["packages"]["find"]["include"],
        "default_testpaths": config["tool"]["pytest"]["ini_options"]["testpaths"],
        "production_imports": imports,
        "production_legacy_imports": references,
        "candidate_file_count": len(candidates),
        "candidate_bytes": sum((root / path).stat().st_size for path in candidates),
        "candidates": candidates,
        "not_covered": [
            "Dynamic imports, subprocesses, external consumers and installed wrappers "
            "need verification.",
            "This source-only audit does not inspect, migrate, or delete user databases.",
            "Candidates are not approved removals until replacement validation is complete.",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
