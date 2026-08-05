from typing import TypedDict, Optional, Any, List, Dict
from datetime import datetime


class AssetItem(TypedDict, total=False):
    name: str
    description: str
    prompt: str
    image_path: Optional[str]
    category: str


class CharacterAsset(AssetItem):
    category: str = "character"


class SceneAsset(AssetItem):
    category: str = "scene"


class PropAsset(AssetItem):
    category: str = "prop"


class ShotInfo(TypedDict, total=False):
    shot_id: str
    group_id: str
    shot_type: str
    duration: str
    framing: str
    camera_movement: str
    content: str
    dialogue: str
    visual_style: str
    audio_notes: str
    prompt: str


class ShotGroup(TypedDict, total=False):
    group_id: str
    group_name: str
    estimated_duration: str
    narrative_function: str
    transition: str
    status: str
    shots: List[ShotInfo]


class SceneInfo(TypedDict, total=False):
    scene_id: str
    scene_name: str
    location: str
    time_of_day: str
    characters: List[str]
    props: List[str]
    description: str


class ConsistencyAnchor(TypedDict, total=False):
    anchor_type: str
    anchor_name: str
    anchor_value: str
    affected_scenes: List[str]
    notes: str


class VideoSegment(TypedDict, total=False):
    segment_id: str
    shot_id: str
    prompt: str
    video_path: Optional[str]
    status: str
    duration: float


class WorkflowState(TypedDict, total=False):
    episode_id: str
    episode_title: str
    
    input_file_path: str
    script_content: str
    
    assets_generated: bool
    character_assets: List[CharacterAsset]
    scene_assets: List[SceneAsset]
    prop_assets: List[PropAsset]
    asset_prompts: Dict[str, List[str]]
    asset_table_path: Optional[str]
    
    step1_completed: bool
    scene_table: List[SceneInfo]
    camera_positions: List[Dict[str, Any]]
    opening_state: Dict[str, Any]
    shot_groups: List[ShotGroup]
    step1_output_path: Optional[str]
    
    step2_completed: bool
    consistency_anchors: List[ConsistencyAnchor]
    step2_output_path: Optional[str]
    
    step3_completed: bool
    optimized_prompts: List[Dict[str, Any]]
    step3_output_path: Optional[str]
    
    videos_generated: bool
    video_segments: List[VideoSegment]
    video_output_dir: Optional[str]
    
    videos_merged: bool
    final_video_path: Optional[str]
    
    errors: List[str]
    current_node: str
    execution_log: List[Dict[str, Any]]
    created_at: str
    updated_at: str


def create_initial_state(episode_id: str, episode_title: str, input_file_path: str) -> WorkflowState:
    return WorkflowState(
        episode_id=episode_id,
        episode_title=episode_title,
        input_file_path=input_file_path,
        script_content="",

        assets_generated=False,
        character_assets=[],
        scene_assets=[],
        prop_assets=[],
        asset_prompts={},
        asset_table_path=None,

        step1_completed=False,
        scene_table=[],
        camera_positions=[],
        opening_state={},
        shot_groups=[],
        step1_output_path=None,

        step2_completed=False,
        consistency_anchors=[],
        step2_output_path=None,

        step3_completed=False,
        optimized_prompts=[],
        step3_output_path=None,

        videos_generated=False,
        video_segments=[],
        video_output_dir=None,

        videos_merged=False,
        final_video_path=None,

        errors=[],
        current_node="init",
        execution_log=[],
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
    )


def state_to_dict(state: WorkflowState) -> dict:
    """将 WorkflowState 转为普通 dict，用于 JSON 序列化持久化。"""
    return dict(state)


def state_from_dict(data: dict) -> WorkflowState:
    """从持久化的 dict 恢复 WorkflowState。"""
    return WorkflowState(**data)
