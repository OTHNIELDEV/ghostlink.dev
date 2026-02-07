from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class OptimizationBanditArm(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    site_id: int = Field(foreign_key="site.id", index=True)
    action_id: int = Field(foreign_key="optimizationaction.id", index=True)
    arm_key: str = Field(index=True)

    alpha: float = Field(default=1.0)
    beta: float = Field(default=1.0)
    pulls: int = Field(default=0, index=True)
    cumulative_reward: float = Field(default=0.0)
    average_reward: float = Field(default=0.0, index=True)
    last_reward: Optional[float] = None
    last_reward_at: Optional[datetime] = None
    metadata_json: str = Field(default="{}")

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


class OptimizationBanditDecision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    site_id: int = Field(foreign_key="site.id", index=True)
    created_by_user_id: int = Field(foreign_key="user.id", index=True)
    selected_action_id: Optional[int] = Field(default=None, foreign_key="optimizationaction.id", index=True)
    selected_arm_key: Optional[str] = Field(default=None, index=True)
    strategy: str = Field(default="thompson", index=True)
    scored_candidates_json: str = Field(default="[]")
    context_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class BrandEntity(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    created_by_user_id: int = Field(foreign_key="user.id", index=True)
    entity_type: str = Field(index=True)
    name: str = Field(index=True)
    canonical_key: str = Field(index=True)
    description: Optional[str] = None
    attributes_json: str = Field(default="{}")
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


class BrandEntityRelation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    from_entity_id: int = Field(foreign_key="brandentity.id", index=True)
    to_entity_id: int = Field(foreign_key="brandentity.id", index=True)
    relation_type: str = Field(index=True)
    weight: float = Field(default=1.0)
    metadata_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class SchemaDraft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    site_id: int = Field(foreign_key="site.id", index=True)
    generated_by_user_id: int = Field(foreign_key="user.id", index=True)
    applied_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    status: str = Field(default="draft", index=True)
    schema_type: str = Field(default="GraphComposite", index=True)
    json_ld_content: str = Field(default="{}")
    source_json: str = Field(default="{}")
    applied_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


class CompliancePolicy(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    created_by_user_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(index=True)
    version: int = Field(default=1)
    enforcement_mode: str = Field(default="advisory", index=True)  # advisory | blocking
    target_scope: str = Field(default="site_content", index=True)
    rules_json: str = Field(default="{}")
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
    )


class ComplianceCheckRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    policy_id: int = Field(foreign_key="compliancepolicy.id", index=True)
    site_id: Optional[int] = Field(default=None, foreign_key="site.id", index=True)
    checked_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)

    target_type: str = Field(default="site", index=True)
    target_ref: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="passed", index=True)
    summary_json: str = Field(default="{}")
    violations_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class EdgeArtifact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    site_id: int = Field(foreign_key="site.id", index=True)
    created_by_user_id: int = Field(foreign_key="user.id", index=True)
    artifact_type: str = Field(index=True)  # jsonld | llms_txt | bridge_script
    content_sha256: str = Field(index=True)
    content_body: str = Field(default="")
    metadata_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class EdgeDeployment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    site_id: int = Field(foreign_key="site.id", index=True)
    artifact_id: int = Field(foreign_key="edgeartifact.id", index=True)
    deployed_by_user_id: int = Field(foreign_key="user.id", index=True)
    channel: str = Field(default="production", index=True)  # staging | production
    status: str = Field(default="active", index=True)  # active | superseded | rolled_back
    rolled_back_from_deployment_id: Optional[int] = Field(default=None, index=True)
    metadata_json: str = Field(default="{}")
    deployed_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    rolled_back_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
