from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BITABLE_DIR = "bitable"
DRIVE_DIR = "drive/Radar内容库"


class LocalFeishuStore:
    """Local adapter that mirrors Feishu Drive + Bitable semantics for Hermes dry-runs."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.bitable_root = self.root / BITABLE_DIR
        self.drive_root = self.root / DRIVE_DIR
        self.ensure_structure()

    def ensure_structure(self) -> None:
        self.bitable_root.mkdir(parents=True, exist_ok=True)
        for relative in [
            "00_运行报告/crawler",
            "00_运行报告/organizer",
            "00_运行报告/publisher",
            "01_待整理",
            "02_待审核",
            "03_待发布",
            "04_已发布",
            "99_失败",
        ]:
            (self.drive_root / relative).mkdir(parents=True, exist_ok=True)

    def table_path(self, table_name: str) -> Path:
        return self.bitable_root / f"{table_name}.json"

    def read_table(self, table_name: str) -> list[dict[str, Any]]:
        path = self.table_path(table_name)
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def write_table(self, table_name: str, rows: list[dict[str, Any]]) -> None:
        path = self.table_path(table_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert_record(self, table_name: str, unique_key: str, record: dict[str, Any]) -> dict[str, Any]:
        rows = self.read_table(table_name)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        record = {**record, "unique_key": unique_key, "updated_at": now}
        for index, row in enumerate(rows):
            if row.get("unique_key") == unique_key:
                rows[index] = {**row, **record}
                self.write_table(table_name, rows)
                return rows[index]
        record.setdefault("record_id", f"{table_name}_{len(rows) + 1}")
        record.setdefault("created_at", now)
        rows.append(record)
        self.write_table(table_name, rows)
        return record

    def query_records(self, table_name: str, **filters: Any) -> list[dict[str, Any]]:
        rows = self.read_table(table_name)
        result = []
        for row in rows:
            if all(row.get(key) == value for key, value in filters.items()):
                result.append(row)
        return result

    def write_markdown(self, relative_path: Path, content: str) -> dict[str, str]:
        path = self.drive_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {
            "markdown_file_token": str(relative_path),
            "markdown_file_url": path.as_uri(),
            "markdown_path": str(relative_path),
        }

    def read_markdown(self, markdown_path: str) -> str:
        return (self.drive_root / markdown_path).read_text(encoding="utf-8")

    def update_markdown(self, markdown_path: str, content: str) -> None:
        (self.drive_root / markdown_path).write_text(content, encoding="utf-8")

    def move_markdown(self, markdown_path: str, target_status_folder: str) -> dict[str, str]:
        old_path = self.drive_root / markdown_path
        parts = Path(markdown_path).parts
        new_relative = Path(target_status_folder, *parts[1:]) if parts else Path(target_status_folder, old_path.name)
        new_path = self.drive_root / new_relative
        new_path.parent.mkdir(parents=True, exist_ok=True)
        if old_path.exists() and old_path != new_path:
            shutil.move(str(old_path), str(new_path))
        return {
            "markdown_file_token": str(new_relative),
            "markdown_file_url": new_path.as_uri(),
            "markdown_path": str(new_relative),
        }

    def write_run_report(self, agent_name: str, run_id: str, report: dict[str, Any]) -> dict[str, str]:
        agent_dir = {"content_crawler": "crawler", "content_organizer": "organizer", "content_publisher": "publisher"}.get(agent_name, agent_name)
        relative = Path("00_运行报告") / agent_dir / f"{run_id}.json"
        path = self.drive_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"report_path": str(relative), "report_url": path.as_uri()}
