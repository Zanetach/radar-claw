#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HERMES_HOME = Path.home() / ".hermes"
CONFIG_PATH = HERMES_HOME / "config.yaml"
SKILL_SOURCES = {
    "radar-data-collection": ROOT / "tools" / "hermes_skills" / "radar-data-collection" / "SKILL.md",
    "radar-content-workflow": ROOT / "tools" / "hermes_skills" / "radar-content-workflow" / "SKILL.md",
}
MCP_SERVER = ROOT / "tools" / "radar_mcp_server.py"


def python_for_hermes() -> str:
    candidate = HERMES_HOME / "hermes-agent" / "venv" / "bin" / "python"
    return str(candidate if candidate.exists() else Path("/usr/bin/python3"))


def radar_mcp_block(base_url: str) -> str:
    return "\n".join(
        [
            "mcp_servers:",
            "  radar:",
            f"    command: {python_for_hermes()}",
            "    args:",
            f"    - {MCP_SERVER}",
            "    env:",
            f"      RADAR_BASE_URL: {base_url}",
            "    enabled: true",
            "",
        ]
    )


def install_skill() -> None:
    for name, source in SKILL_SOURCES.items():
        target = HERMES_HOME / "skills" / name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def ensure_config(base_url: str) -> str:
    HERMES_HOME.mkdir(parents=True, exist_ok=True)
    existing = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else ""
    block = radar_mcp_block(base_url)
    if "mcp_servers:" not in existing:
        CONFIG_PATH.write_text((existing.rstrip() + "\n\n" + block).lstrip(), encoding="utf-8")
        return "added_mcp_servers"
    if "  radar:" not in existing or "radar_mcp_server.py" not in existing:
        lines = existing.rstrip().splitlines()
        output: list[str] = []
        inserted = False
        for line in lines:
            output.append(line)
            if line.strip() == "mcp_servers:" and not inserted:
                output.extend(block.splitlines()[1:])
                inserted = True
        CONFIG_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
        return "added_radar_server"
    return "already_configured"


def check_radar(base_url: str) -> str:
    try:
        result = subprocess.run(
            ["curl", "--noproxy", "*", "-fsS", f"{base_url.rstrip('/')}/api/summary"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:  # pragma: no cover - diagnostic only
        return f"unreachable: {exc}"
    return "reachable" if result.returncode == 0 else f"unreachable: {result.stderr.strip() or result.returncode}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Radar MCP and skill into Hermes Agent.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8780")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    status = "check_only"
    if not args.check_only:
        install_skill()
        status = ensure_config(args.base_url)

    print(f"Hermes home: {HERMES_HOME}")
    for name in SKILL_SOURCES:
        target = HERMES_HOME / "skills" / name / "SKILL.md"
        print(f"Radar skill {name}: {target} ({'exists' if target.exists() else 'missing'})")
    print(f"Radar MCP config: {status}")
    print(f"Radar API: {check_radar(args.base_url)}")
    print("Hermes command: hermes --skills radar-data-collection")
    print("If Hermes is already running, reload MCP inside Hermes with: /reload-mcp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
