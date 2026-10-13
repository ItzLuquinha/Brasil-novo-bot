import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_python_distribution_includes_the_rest_api_package() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    included = config["tool"]["setuptools"]["packages"]["find"]["include"]
    assert "api*" in included


def test_local_infrastructure_ports_are_not_published_to_the_lan() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:5432:5432"' in compose
    assert '"127.0.0.1:6379:6379"' in compose
    assert '"5432:5432"' not in compose
    assert '"6379:6379"' not in compose


def test_tailwind_v4_uses_vite_plugin_without_legacy_postcss_config() -> None:
    package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    dev_dependencies = package.get("devDependencies", {})
    assert dev_dependencies.get("tailwindcss", "").lstrip("^~").startswith("4.")
    assert "@tailwindcss/vite" in dev_dependencies
    assert not (ROOT / "web" / "postcss.config.js").exists()

    vite = (ROOT / "web" / "vite.config.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "src" / "index.css").read_text(encoding="utf-8")
    assert "@tailwindcss/vite" in vite
    assert "tailwindcss()" in vite
    assert '@import "tailwindcss";' in css
    assert '@config "../tailwind.config.js";' in css
