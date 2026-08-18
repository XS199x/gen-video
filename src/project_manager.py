"""
项目管理 — SQLite 持久化，支持项目 CRUD、状态存储、步骤追踪。

每个项目对应一个 SQLite 行，WorkflowState 以 JSON 形式存储在 project_state 表中。
"""

import json
import os
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .state import WorkflowState, state_to_dict, state_from_dict, create_initial_state
from . import lineage
from .logger import get_logger

logger = get_logger("project_manager")

DB_DIR = Path("./data")
UPLOAD_DIR = Path("./uploads")
PROJECTS_DIR = Path("./projects")

# 步骤常量统一复用血缘单一权威（src/lineage.py），不再本地维护副本。
STEP_NAMES = lineage.STEP_ORDER
STEP_LABELS = lineage.STEP_LABELS
PREVIEW_STEPS = lineage.PREVIEW_STEPS
GENERATE_STEPS = lineage.GENERATE_STEPS


class ProjectManager:
    """线程安全的 SQLite 项目管理器。"""

    def __init__(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

        self._db_path = DB_DIR / "projects.db"
        self._lock = threading.Lock()
        self._init_db()

    # ─── 数据库初始化 ────────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS projects (
                        id          TEXT PRIMARY KEY,
                        name        TEXT NOT NULL DEFAULT '',
                        episode_id  TEXT NOT NULL DEFAULT '01',
                        episode_title TEXT NOT NULL DEFAULT '',
                        status      TEXT NOT NULL DEFAULT 'created',
                        input_file  TEXT DEFAULT '',
                        created_at  TEXT NOT NULL,
                        updated_at  TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS project_state (
                        project_id  TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                        state_json  TEXT NOT NULL DEFAULT '{}'
                    );

                    CREATE TABLE IF NOT EXISTS project_steps (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        step_name   TEXT NOT NULL,
                        status      TEXT NOT NULL DEFAULT 'pending',
                        stale       INTEGER NOT NULL DEFAULT 0,
                        started_at  TEXT,
                        finished_at TEXT,
                        error       TEXT DEFAULT '',
                        result_summary TEXT DEFAULT '',
                        UNIQUE(project_id, step_name)
                    );
                """)
                # 幂等迁移：为早于 stale 列的旧库补列（新库建表已含，不重复）。
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(project_steps)").fetchall()}
                if "stale" not in cols:
                    conn.execute("ALTER TABLE project_steps ADD COLUMN stale INTEGER NOT NULL DEFAULT 0")
                conn.commit()
            finally:
                conn.close()

    # ─── 项目 CRUD ──────────────────────────────────────────────

    def create_project(self, name: str = "", episode_id: str = "01",
                       episode_title: str = "") -> Dict[str, Any]:
        pid = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO projects (id, name, episode_id, episode_title, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'created', ?, ?)",
                    (pid, name, episode_id, episode_title, now, now),
                )

                initial_state = create_initial_state(episode_id, episode_title, "")
                conn.execute(
                    "INSERT INTO project_state (project_id, state_json) VALUES (?, ?)",
                    (pid, json.dumps(state_to_dict(initial_state), ensure_ascii=False)),
                )

                for sn in STEP_NAMES:
                    conn.execute(
                        "INSERT INTO project_steps (project_id, step_name, status) VALUES (?, ?, 'pending')",
                        (pid, sn),
                    )

                conn.commit()
                logger.info("项目已创建: %s", pid)
            finally:
                conn.close()

        return self.get_project(pid)

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                return None

            project = dict(row)

            state_row = conn.execute(
                "SELECT state_json FROM project_state WHERE project_id = ?", (project_id,)
            ).fetchone()
            project["state"] = json.loads(state_row["state_json"]) if state_row else {}

            steps = conn.execute(
                "SELECT * FROM project_steps WHERE project_id = ? ORDER BY id", (project_id,)
            ).fetchall()
            project["steps"] = [dict(s) for s in steps]

            return project
        finally:
            conn.close()

    def list_projects(self) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ).fetchall()
            projects = []
            for row in rows:
                p = dict(row)
                steps = conn.execute(
                    "SELECT step_name, status, stale FROM project_steps WHERE project_id = ? ORDER BY id",
                    (p["id"],),
                ).fetchall()
                p["steps"] = [dict(s) for s in steps]
                projects.append(p)
            return projects
        finally:
            conn.close()

    def delete_project(self, project_id: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
                conn.commit()
                deleted = cursor.rowcount > 0
            finally:
                conn.close()

        if deleted:
            # 清理文件
            project_dir = PROJECTS_DIR / project_id
            if project_dir.exists():
                shutil.rmtree(str(project_dir), ignore_errors=True)
            output_dir = Path("./outputs") / project_id
            if output_dir.exists():
                shutil.rmtree(str(output_dir), ignore_errors=True)
            logger.info("项目已删除: %s", project_id)

        return deleted

    def update_project(self, project_id: str, **kwargs) -> bool:
        if not kwargs:
            return False
        kwargs["updated_at"] = datetime.now().isoformat()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [project_id]

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(f"UPDATE projects SET {sets} WHERE id = ?", vals)
                conn.commit()
            finally:
                conn.close()
        return True

    # ─── 状态持久化 ─────────────────────────────────────────────

    def save_state(self, project_id: str, state: WorkflowState):
        state_json = json.dumps(state_to_dict(state), ensure_ascii=False)
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO project_state (project_id, state_json) VALUES (?, ?)",
                    (project_id, state_json),
                )
                conn.execute(
                    "UPDATE projects SET updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), project_id),
                )
                conn.commit()
            finally:
                conn.close()

    def load_state(self, project_id: str) -> Optional[WorkflowState]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT state_json FROM project_state WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row and row["state_json"]:
                return state_from_dict(json.loads(row["state_json"]))
            return None
        finally:
            conn.close()

    # ─── 步骤追踪 ───────────────────────────────────────────────

    def set_step_status(self, project_id: str, step_name: str, status: str,
                        error: str = "", result_summary: str = ""):
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                if status == "running":
                    conn.execute(
                        "UPDATE project_steps SET status=?, started_at=?, error='', result_summary='' "
                        "WHERE project_id=? AND step_name=?",
                        (status, now, project_id, step_name),
                    )
                else:
                    conn.execute(
                        "UPDATE project_steps SET status=?, finished_at=?, error=?, result_summary=? "
                        "WHERE project_id=? AND step_name=?",
                        (status, now, error, result_summary, project_id, step_name),
                    )
                conn.execute(
                    "UPDATE projects SET updated_at=? WHERE id=?",
                    (now, project_id),
                )
                conn.commit()
            finally:
                conn.close()

    def reset_steps_from(self, project_id: str, step_name: str):
        """将指定步骤及其后续步骤重置为 pending（并清脏，回到干净起点）。"""
        idx = STEP_NAMES.index(step_name) if step_name in STEP_NAMES else 0
        with self._lock:
            conn = self._get_conn()
            try:
                for sn in STEP_NAMES[idx:]:
                    conn.execute(
                        "UPDATE project_steps SET status='pending', stale=0, started_at=NULL, "
                        "finished_at=NULL, error='', result_summary='' "
                        "WHERE project_id=? AND step_name=?",
                        (project_id, sn),
                    )
                conn.execute(
                    "UPDATE projects SET updated_at=?, status='editing' WHERE id=?",
                    (datetime.now().isoformat(), project_id),
                )
                conn.commit()
            finally:
                conn.close()

    def set_step_stale(self, project_id: str, step_names, stale: bool = True):
        """结构化脏标记：把一个或多个步骤置脏/清脏。

        step_names 可以是单个步骤名或步骤名列表。脏 = 上游内容已变，
        该步已生成的产物与最新输入不一致，需要重跑（但产物本身保留）。
        """
        if isinstance(step_names, str):
            step_names = [step_names]
        if not step_names:
            return
        flag = 1 if stale else 0
        now = datetime.now().isoformat()
        with self._lock:
            conn = self._get_conn()
            try:
                for sn in step_names:
                    conn.execute(
                        "UPDATE project_steps SET stale=? WHERE project_id=? AND step_name=?",
                        (flag, project_id, sn),
                    )
                conn.execute(
                    "UPDATE projects SET updated_at=? WHERE id=?",
                    (now, project_id),
                )
                conn.commit()
            finally:
                conn.close()

    def get_step_status(self, project_id: str, step_name: str) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM project_steps WHERE project_id=? AND step_name=?",
                (project_id, step_name),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ─── 文件管理 ────────────────────────────────────────────────

    def get_project_dir(self, project_id: str) -> Path:
        d = PROJECTS_DIR / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_upload(self, project_id: str, file_data: bytes, filename: str) -> str:
        """保存上传的剧本文件，返回存储路径。"""
        ext = os.path.splitext(filename)[1] or ".docx"
        stored_name = f"script{ext}"
        project_dir = self.get_project_dir(project_id)
        filepath = project_dir / stored_name
        with open(filepath, "wb") as f:
            f.write(file_data)

        self.update_project(project_id, input_file=str(filepath))
        logger.info("剧本已保存: %s", filepath)
        return str(filepath)

    def get_output_dir(self, project_id: str) -> str:
        d = Path("./outputs") / project_id
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def get_step_result(self, project_id: str, step_name: str) -> Dict[str, Any]:
        """获取步骤结果数据，供前端展示。"""
        state = self.load_state(project_id)
        result: Dict[str, Any] = {"step": step_name, "label": STEP_LABELS.get(step_name, step_name)}

        if state is None:
            result["status"] = "pending"
            return result

        step_status = self.get_step_status(project_id, step_name)
        if step_status:
            result["status"] = step_status["status"]
            result["error"] = step_status.get("error", "")
            result["stale"] = bool(step_status.get("stale", 0))
        else:
            result["status"] = "pending"
            result["stale"] = False

        if step_name == "parse_docx":
            result["script_length"] = len(state.get("script_content", ""))
            chars = state.get("parsed_characters", [])
            scenes = state.get("parsed_scenes", [])
            result["characters"] = [c.get("name", "") for c in chars]
            result["scenes"] = [s.get("name", "") for s in scenes]
            result["character_count"] = len(chars)
            result["scene_count"] = len(scenes)

        elif step_name == "generate_asset_package":
            result["characters"] = [
                {"name": a.get("name", ""), "description": a.get("description", "")[:100],
                 "image_path": a.get("image_path", ""), "image_generated": a.get("image_generated", False),
                 "image_status": a.get("image_status", "")}
                for a in state.get("character_assets", [])
            ]
            result["scenes"] = [
                {"name": a.get("name", ""), "description": a.get("description", "")[:100],
                 "image_path": a.get("image_path", ""), "image_generated": a.get("image_generated", False),
                 "image_status": a.get("image_status", "")}
                for a in state.get("scene_assets", [])
            ]
            result["props"] = [
                {"name": a.get("name", ""), "description": a.get("description", "")[:100],
                 "image_path": a.get("image_path", ""), "image_generated": a.get("image_generated", False),
                 "image_status": a.get("image_status", "")}
                for a in state.get("prop_assets", [])
            ]

        elif step_name == "step1_storyboard":
            groups = state.get("shot_groups", [])
            result["group_count"] = len(groups)
            result["shot_count"] = sum(len(g.get("shots", [])) for g in groups)
            result["groups"] = [
                {
                    "group_id": g.get("group_id", ""),
                    "group_name": g.get("group_name", ""),
                    "shot_count": len(g.get("shots", [])),
                    "shots": [
                        {"shot_id": s.get("shot_id", ""), "content": s.get("content", "")[:120]}
                        for s in g.get("shots", [])
                    ],
                }
                for g in groups[:20]  # 限制返回数量
            ]

        elif step_name == "step2_consistency":
            anchors = state.get("consistency_anchors", [])
            result["anchor_count"] = len(anchors)
            result["anchors"] = [
                {"name": a.get("anchor_name", ""), "value": a.get("anchor_value", "")[:200]}
                for a in anchors[:10]
            ]

        elif step_name == "step3_optimize_prompts":
            prompts = state.get("optimized_prompts", [])
            result["group_count"] = len(prompts)
            result["total_shots"] = sum(len(g.get("shots", [])) for g in prompts)
            result["prompts"] = [
                {
                    "group_name": g.get("group_name", ""),
                    "shots": [
                        {"shot_name": s.get("shot_name", ""), "prompt": s.get("prompt", "")[:200]}
                        for s in g.get("shots", [])
                    ],
                }
                for g in prompts[:10]
            ]

        elif step_name == "generate_videos":
            segs = state.get("video_segments", [])
            ok = sum(1 for s in segs if s.get("status") == "completed")
            fail = sum(1 for s in segs if s.get("status") == "failed")
            result["total_segments"] = len(segs)
            result["completed"] = ok
            result["failed"] = fail
            result["segments"] = [
                {
                    "segment_id": s.get("segment_id", ""),
                    "shot_id": s.get("shot_id", ""),
                    "status": s.get("status", ""),
                    "prompt": s.get("prompt", "")[:100],
                }
                for s in segs[:30]
            ]

        elif step_name == "merge_videos":
            result["final_video"] = state.get("final_video_path", "")

        return result

    def update_state_field(self, project_id: str, field_path: str, value: Any,
                           reset_downstream: bool = True) -> Dict[str, Any]:
        """按点号路径更新 WorkflowState 中的某个字段，持久化并返回新的 editable result。

        field_path 格式: "character_assets.0.description" 或 "optimized_prompts"
        数字段表示数组索引。

        reset_downstream: 编辑内容会使下游步骤失效，默认清空重置。
            但「仅调整顺序」（如拖拽排序交换两个镜头）不改变内容语义，
            应传 False 以避免误清空一致性/提示词等已完成的下游步骤。
        """
        state = self.load_state(project_id)
        if state is None:
            raise ValueError("项目状态不存在")

        state_dict = state_to_dict(state)
        parts = field_path.split(".")

        # 导航到目标字段的父级
        target = state_dict
        for i, part in enumerate(parts[:-1]):
            if isinstance(target, list):
                idx = int(part)
                target = target[idx]
            else:
                target = target[part]

        # 设置值
        last = parts[-1]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value

        # 保存
        self.save_state(project_id, state_from_dict(state_dict))

        # 数据血缘：编辑属于步骤 N 的字段 → N 及其所有下游步骤标脏（保留产物，不清空）。
        # 直到用户显式重跑（redo/run confirm）才覆盖并清脏。
        step_name = lineage.field_to_step(field_path)
        if step_name and reset_downstream:
            affected = lineage.downstream_steps(step_name, include_self=True)
            self.set_step_stale(project_id, affected, stale=True)
            self.update_project(project_id, status="editing")

        logger.info("字段已更新: %s/%s (标脏步骤: %s)",
                    project_id, field_path,
                    step_name if (step_name and reset_downstream) else "无")
        return {"ok": True, "path": field_path}

    def get_editable_result(self, project_id: str, step_name: str) -> Dict[str, Any]:
        """返回步骤的完整可编辑数据，供前端渲染编辑界面。"""
        result = self.get_step_result(project_id, step_name)
        state = self.load_state(project_id)

        if state is None:
            return result

        result["editable"] = True
        result["_raw"] = {}  # 放置完整原始数据

        if step_name == "parse_docx":
            chars = []
            for c in state.get("parsed_characters", []):
                chars.append({"name": c.get("name", ""), "role": c.get("role", ""),
                              "description": c.get("description", "")})
            scenes = []
            for s in state.get("parsed_scenes", []):
                scenes.append({"name": s.get("name", ""), "location": s.get("location", ""),
                               "time_of_day": s.get("time_of_day", "")})
            result["_raw"] = {
                "parsed_characters": chars,
                "parsed_scenes": scenes,
                "script_content": state.get("script_content", ""),
            }

        elif step_name == "generate_asset_package":
            cats = {"character_assets": "characters", "scene_assets": "scenes", "prop_assets": "props"}
            for key, label in cats.items():
                assets = []
                for a in state.get(key, []):
                    assets.append({
                        "name": a.get("name", ""),
                        "description": a.get("description", ""),
                        "prompt": a.get("prompt", ""),
                        "image_path": a.get("image_path", ""),
                        "image_generated": a.get("image_generated", False),
                        "image_status": a.get("image_status", ""),
                        "category": a.get("category", ""),
                    })
                result["_raw"][label] = assets

        elif step_name == "step1_storyboard":
            groups = []
            for g in state.get("shot_groups", []):
                shots = []
                for s in g.get("shots", []):
                    shots.append({
                        "shot_id": s.get("shot_id", ""),
                        "shot_type": s.get("shot_type", ""),
                        "duration": s.get("duration", ""),
                        "framing": s.get("framing", ""),
                        "camera_movement": s.get("camera_movement", ""),
                        "content": s.get("content", ""),
                        "dialogue": s.get("dialogue", ""),
                        "visual_style": s.get("visual_style", ""),
                        "audio_notes": s.get("audio_notes", ""),
                    })
                groups.append({
                    "group_id": g.get("group_id", ""),
                    "group_name": g.get("group_name", ""),
                    "estimated_duration": g.get("estimated_duration", ""),
                    "narrative_function": g.get("narrative_function", ""),
                    "transition": g.get("transition", ""),
                    "shots": shots,
                })
            result["_raw"] = {"shot_groups": groups}

        elif step_name == "step2_consistency":
            anchors = []
            for a in state.get("consistency_anchors", []):
                anchors.append({
                    "anchor_type": a.get("anchor_type", ""),
                    "anchor_name": a.get("anchor_name", ""),
                    "anchor_value": a.get("anchor_value", ""),
                    "affected_scenes": a.get("affected_scenes", []),
                    "notes": a.get("notes", ""),
                })
            result["_raw"] = {"consistency_anchors": anchors}

        elif step_name == "step3_optimize_prompts":
            groups = []
            for g in state.get("optimized_prompts", []):
                shots = []
                for s in g.get("shots", []):
                    shots.append({
                        "shot_name": s.get("shot_name", ""),
                        "description": s.get("description", ""),
                        "prompt": s.get("prompt", ""),
                        "dialogue": s.get("dialogue", ""),
                        "visual_style": s.get("visual_style", ""),
                        "audio": s.get("audio", ""),
                    })
                groups.append({
                    "group_name": g.get("group_name", ""),
                    "material_references": g.get("material_references", []),
                    "character_voices": g.get("character_voices", []),
                    "style_instructions": g.get("style_instructions", []),
                    "shots": shots,
                })
            result["_raw"] = {"optimized_prompts": groups}

        elif step_name == "generate_videos":
            segs = []
            for s in state.get("video_segments", []):
                segs.append({
                    "segment_id": s.get("segment_id", ""),
                    "shot_id": s.get("shot_id", ""),
                    "prompt": s.get("prompt", ""),
                    "video_path": s.get("video_path", ""),
                    "status": s.get("status", ""),
                    "duration": s.get("duration", 0),
                })
            result["_raw"] = {"video_segments": segs}

        elif step_name == "merge_videos":
            result["_raw"] = {"final_video_path": state.get("final_video_path", "")}

        return result

    def duplicate_project(self, project_id: str, new_name: str = "") -> Optional[str]:
        """复制项目（含状态和所有步骤），返回新项目 ID。"""
        original = self.get_project(project_id)
        if not original:
            return None

        new_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        name = new_name or f"{original.get('name', '')} (副本)"

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO projects (id, name, episode_id, episode_title, status, input_file, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 'created', ?, ?, ?)",
                    (new_id, name, original.get("episode_id", "01"),
                     original.get("episode_title", ""), original.get("input_file", ""), now, now),
                )

                # 复制状态
                state_row = conn.execute(
                    "SELECT state_json FROM project_state WHERE project_id = ?", (project_id,)
                ).fetchone()
                if state_row:
                    conn.execute(
                        "INSERT INTO project_state (project_id, state_json) VALUES (?, ?)",
                        (new_id, state_row["state_json"]),
                    )

                # 复制步骤
                for sn in STEP_NAMES:
                    conn.execute(
                        "INSERT INTO project_steps (project_id, step_name, status) VALUES (?, ?, 'pending')",
                        (new_id, sn),
                    )

                conn.commit()
                logger.info("项目已复制: %s -> %s", project_id, new_id)
            finally:
                conn.close()

        return new_id

    def estimate_cost(self, project_id: str) -> Dict[str, Any]:
        """估算视频生成成本。"""
        state = self.load_state(project_id)
        if state is None:
            return {"shot_count": 0, "estimated_cost": "¥0.00", "ready": False}

        prompts = state.get("optimized_prompts", [])
        total_shots = sum(len(g.get("shots", [])) for g in prompts)

        if total_shots == 0:
            return {"shot_count": 0, "estimated_cost": "¥0.00", "ready": False}

        # Kling 大约 ¥0.5-1.0/秒，5秒 = ¥2.5-5/条
        cost_per_shot = 3.0  # 估算值
        estimated = total_shots * cost_per_shot

        return {
            "shot_count": total_shots,
            "estimated_cost": f"¥{estimated:.2f}",
            "cost_per_shot": cost_per_shot,
            "ready": True,
        }


# 全局单例
_instance: Optional[ProjectManager] = None


def get_project_manager() -> ProjectManager:
    global _instance
    if _instance is None:
        _instance = ProjectManager()
    return _instance
