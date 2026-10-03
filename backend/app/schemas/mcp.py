from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class McpToolCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: str | None
    tool_name: str
    status: str
    actor_label: str | None
    article_id: UUID | None
    run_id: UUID | None
    job_id: UUID | None
    request_json: dict
    response_json: dict
    failure_code: str | None
    failure_message: str | None
    duration_ms: int | None
    created_at: datetime
    finished_at: datetime | None
    metadata_json: dict


class McpCapabilitiesRead(BaseModel):
    protocol: str = "mcp"
    endpoint: str = "/mcp"
    transport: str = "streamable_http"
    auth: str = "bearer_agent_access_token"
    tools: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)
    publisher_capabilities: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
