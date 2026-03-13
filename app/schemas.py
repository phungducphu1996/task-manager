from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TaskType(str, Enum):
    story = "story"
    reel = "reel"
    post = "post"


class TaskStatus(str, Enum):
    idea = "idea"
    design = "design"
    ready = "ready"
    posted = "posted"


class TaskChecklistItemIn(BaseModel):
    title: str
    is_done: bool = False
    position: int = 0


class TaskChecklistItemOut(TaskChecklistItemIn):
    id: str

    model_config = ConfigDict(from_attributes=True)


class ChecklistUpdateRequest(BaseModel):
    items: list[TaskChecklistItemIn] = Field(default_factory=list)


class SocialAssetOut(BaseModel):
    id: str
    kind: str
    storage_path: str | None = None
    url: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskCommentCreate(BaseModel):
    content: str
    user_name: str | None = None
    parent_id: str | None = None


class TaskCommentOut(BaseModel):
    id: str
    content: str
    user_id: str | None = None
    parent_id: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskActivityOut(BaseModel):
    id: str
    actor_id: str | None = None
    action: str
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskCreate(BaseModel):
    title: str
    type: TaskType
    quick_note: str | None = Field(default=None, max_length=256)
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    caption: str | None = None
    campaign_name: str | None = None
    campaign_requires_product_url: bool = False
    air_date: datetime | None = None
    status: TaskStatus = TaskStatus.idea
    product_url: str | None = None
    assignee_name: str | None = None
    checklist: list[TaskChecklistItemIn] = Field(default_factory=list)
    media_urls: list[str] = Field(default_factory=list)
    brand: str | None = None
    platform: str | None = None
    created_by_name: str | None = None
    collection_ids: list[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = None
    type: TaskType | None = None
    quick_note: str | None = Field(default=None, max_length=256)
    hashtags: list[str] | None = None
    mentions: list[str] | None = None
    caption: str | None = None
    campaign_name: str | None = None
    campaign_requires_product_url: bool | None = None
    air_date: datetime | None = None
    status: TaskStatus | None = None
    product_url: str | None = None
    assignee_name: str | None = None
    brand: str | None = None
    platform: str | None = None
    collection_ids: list[str] | None = None


class AttachAssetsRequest(BaseModel):
    media_urls: list[str]


class Base64MediaFileIn(BaseModel):
    filename: str
    content_type: str | None = None
    data_base64: str


class Base64MediaUploadRequest(BaseModel):
    files: list[Base64MediaFileIn] = Field(default_factory=list)


class AvatarUploadRequest(BaseModel):
    file: Base64MediaFileIn


class ValidateResult(BaseModel):
    ok: bool
    missing_fields: list[str]


class PrincipalOut(BaseModel):
    user_id: str
    username: str
    name: str | None = None
    role: str
    avatar_url: str | None = None
    is_admin: bool
    is_seller: bool


class LoginRequest(BaseModel):
    username: str
    password: str


class SellerOut(BaseModel):
    id: str
    username: str
    name: str | None = None
    role: str | None = None
    avatar_url: str | None = None
    is_active: bool = True


class UserCreate(BaseModel):
    name: str
    username: str
    role: str = "content"
    avatar_url: str | None = None
    zalo_user_id: str | None = None
    password: str = Field(min_length=6, max_length=128)
    is_active: bool = True


class UserUpdate(BaseModel):
    name: str | None = None
    username: str | None = None
    role: str | None = None
    avatar_url: str | None = None
    zalo_user_id: str | None = None
    is_active: bool | None = None


class UserPasswordUpdate(BaseModel):
    password: str = Field(min_length=6, max_length=128)


class ProfileUpdate(BaseModel):
    name: str | None = None
    username: str | None = None
    avatar_url: str | None = None
    zalo_user_id: str | None = None


class ProfilePasswordUpdate(BaseModel):
    current_password: str | None = Field(default=None, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class UserOut(BaseModel):
    id: str
    name: str
    username: str | None = None
    role: str
    avatar_url: str | None = None
    zalo_user_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CampaignCreate(BaseModel):
    name: str
    status: str = "planning"
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    link_url: str | None = None
    color: str | None = None
    icon: str | None = None
    requires_product_url: bool = False
    brand: str | None = None
    platform: str | None = None


class CampaignUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    link_url: str | None = None
    color: str | None = None
    icon: str | None = None
    requires_product_url: bool | None = None
    brand: str | None = None
    platform: str | None = None


class CampaignOut(BaseModel):
    id: str
    name: str
    status: str
    start_date: str | None = None
    end_date: str | None = None
    description: str | None = None
    link_url: str | None = None
    color: str | None = None
    icon: str | None = None
    requires_product_url: bool
    brand: str | None = None
    platform: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CollectionCreate(BaseModel):
    name: str
    description: str | None = None
    color: str | None = None
    is_active: bool = True


class CollectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None
    is_active: bool | None = None


class CollectionTaskUpdate(BaseModel):
    task_ids: list[str] = Field(default_factory=list)


class CollectionOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    color: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HashtagGroupCreate(BaseModel):
    name: str
    scope: str = "global"
    campaign_name: str | None = None
    task_type: TaskType | None = None
    is_active: bool = True


class HashtagGroupUpdate(BaseModel):
    name: str | None = None
    scope: str | None = None
    campaign_name: str | None = None
    task_type: TaskType | None = None
    is_active: bool | None = None


class HashtagGroupOut(BaseModel):
    id: str
    name: str
    scope: str
    campaign_id: str | None = None
    task_type: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HashtagEntryCreate(BaseModel):
    group_id: str
    tag: str
    is_active: bool = True


class HashtagEntryUpdate(BaseModel):
    tag: str | None = None
    is_active: bool | None = None


class HashtagEntryOut(BaseModel):
    id: str
    group_id: str
    tag: str
    normalized_tag: str
    is_active: bool
    usage_count: int
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskOut(BaseModel):
    id: str
    brand: str | None = None
    platform: str | None = None
    type: str
    title: str
    quick_note: str | None = None
    caption: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    product_url: str | None = None
    campaign_id: str | None = None
    air_date: datetime | None = None
    status: str
    assignee_id: str | None = None
    assignee_name: str | None = None
    campaign_name: str | None = None
    campaign_color: str | None = None
    campaign_icon: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    collections: list[CollectionOut] = Field(default_factory=list)
    assets: list[SocialAssetOut] = Field(default_factory=list)
    comments: list[TaskCommentOut] = Field(default_factory=list)
    checklist_items: list[TaskChecklistItemOut] = Field(default_factory=list)
    activity_logs: list[TaskActivityOut] = Field(default_factory=list)
    validation_result: ValidateResult | None = Field(
        default=None,
        alias="validate",
        serialization_alias="validate",
    )

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class BotWebhookRequest(BaseModel):
    sender_id: str
    sender_name: str | None = None
    text: str | None = None
    media_urls: list[str] = Field(default_factory=list)


class BotWebhookResponse(BaseModel):
    message: str
    task_id: str | None = None
    validation_result: ValidateResult | None = Field(
        default=None,
        alias="validate",
        serialization_alias="validate",
    )
    dashboard_url: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class ReminderRunRequest(BaseModel):
    now_utc: datetime | None = None
    limit: int = 200


class ReminderJobResult(BaseModel):
    job_id: str
    task_id: str
    job_type: str
    status: str
    message: str


class ReminderRunResponse(BaseModel):
    processed: int
    results: list[ReminderJobResult]


class AnalyticsBasic(BaseModel):
    total_this_week: int
    overdue_count: int
    campaign_count: int
    top_assignees: list[dict]


class ZaloSettingsOut(BaseModel):
    social_group_chat_id: str | None = None
    source: str = "none"


class ZaloSettingsUpdate(BaseModel):
    social_group_chat_id: str | None = None
