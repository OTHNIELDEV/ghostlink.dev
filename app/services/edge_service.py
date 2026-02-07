import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.innovation_plus import EdgeArtifact, EdgeDeployment
from app.models.site import Site


class EdgeService:
    VALID_ARTIFACT_TYPES = {"jsonld", "llms_txt", "bridge_script"}
    VALID_CHANNELS = {"staging", "production"}

    def _build_bridge_script_content(self, site: Site) -> str:
        raw_json_ld = site.json_ld or site.json_ld_content or ""
        encoded_json_ld = json.dumps(raw_json_ld)
        return f"""
(function() {{
    const rawJsonLd = {encoded_json_ld};
    let jsonLdData = null;
    try {{
        jsonLdData = rawJsonLd ? JSON.parse(rawJsonLd) : null;
    }} catch (_) {{
        jsonLdData = null;
    }}

    if (jsonLdData) {{
        const script = document.createElement('script');
        script.type = 'application/ld+json';
        script.text = JSON.stringify(jsonLdData);
        document.head.appendChild(script);
    }}
}})();
"""

    def _build_content(self, site: Site, artifact_type: str) -> str:
        if artifact_type == "jsonld":
            return site.json_ld or site.json_ld_content or "{}"
        if artifact_type == "llms_txt":
            return site.llms_txt or site.llms_txt_content or ""
        if artifact_type == "bridge_script":
            return self._build_bridge_script_content(site)
        raise ValueError("Unsupported artifact_type")

    async def get_site(self, session: AsyncSession, org_id: int, site_id: int) -> Optional[Site]:
        row = await session.exec(
            select(Site).where(
                and_(
                    Site.org_id == org_id,
                    Site.id == site_id,
                )
            )
        )
        return row.first()

    async def build_artifact(
        self,
        session: AsyncSession,
        org_id: int,
        site: Site,
        user_id: int,
        artifact_type: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> EdgeArtifact:
        normalized_type = (artifact_type or "").strip().lower()
        if normalized_type not in self.VALID_ARTIFACT_TYPES:
            raise ValueError("artifact_type must be one of jsonld, llms_txt, bridge_script")

        content = self._build_content(site, normalized_type)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

        artifact = EdgeArtifact(
            org_id=org_id,
            site_id=site.id,
            created_by_user_id=user_id,
            artifact_type=normalized_type,
            content_sha256=digest,
            content_body=content,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=True),
        )
        session.add(artifact)
        await session.commit()
        await session.refresh(artifact)
        return artifact

    async def deploy_artifact(
        self,
        session: AsyncSession,
        org_id: int,
        site_id: int,
        artifact_id: int,
        user_id: int,
        channel: str = "production",
        metadata: Optional[dict[str, Any]] = None,
    ) -> EdgeDeployment:
        normalized_channel = (channel or "production").strip().lower()
        if normalized_channel not in self.VALID_CHANNELS:
            raise ValueError("channel must be production or staging")

        artifact = (
            await session.exec(
                select(EdgeArtifact).where(
                    and_(
                        EdgeArtifact.id == artifact_id,
                        EdgeArtifact.org_id == org_id,
                        EdgeArtifact.site_id == site_id,
                    )
                )
            )
        ).first()
        if not artifact:
            raise ValueError("artifact not found")

        active_rows = (
            await session.exec(
                select(EdgeDeployment).where(
                    and_(
                        EdgeDeployment.org_id == org_id,
                        EdgeDeployment.site_id == site_id,
                        EdgeDeployment.channel == normalized_channel,
                        EdgeDeployment.status == "active",
                    )
                )
            )
        ).all()
        for row in active_rows:
            row.status = "superseded"
            session.add(row)

        deployment = EdgeDeployment(
            org_id=org_id,
            site_id=site_id,
            artifact_id=artifact_id,
            deployed_by_user_id=user_id,
            channel=normalized_channel,
            status="active",
            metadata_json=json.dumps(metadata or {}, ensure_ascii=True),
            deployed_at=datetime.utcnow(),
        )
        session.add(deployment)
        await session.commit()
        await session.refresh(deployment)
        return deployment

    async def list_deployments(
        self,
        session: AsyncSession,
        org_id: int,
        site_id: int,
        channel: Optional[str] = None,
        limit: int = 50,
    ) -> list[EdgeDeployment]:
        query = select(EdgeDeployment).where(
            and_(
                EdgeDeployment.org_id == org_id,
                EdgeDeployment.site_id == site_id,
            )
        )
        if channel:
            query = query.where(EdgeDeployment.channel == channel)
        query = query.order_by(EdgeDeployment.deployed_at.desc()).limit(min(max(limit, 1), 200))
        rows = await session.exec(query)
        return rows.all()

    async def get_active_artifact(
        self,
        session: AsyncSession,
        site_id: int,
        channel: str = "production",
        artifact_type: Optional[str] = None,
    ) -> Optional[EdgeArtifact]:
        deployment = (
            await session.exec(
                select(EdgeDeployment)
                .where(
                    and_(
                        EdgeDeployment.site_id == site_id,
                        EdgeDeployment.channel == channel,
                        EdgeDeployment.status == "active",
                    )
                )
                .order_by(EdgeDeployment.deployed_at.desc())
            )
        ).first()
        if not deployment:
            return None

        artifact = await session.get(EdgeArtifact, deployment.artifact_id)
        if not artifact:
            return None
        if artifact_type and artifact.artifact_type != artifact_type:
            return None
        return artifact

    async def rollback_to_deployment(
        self,
        session: AsyncSession,
        org_id: int,
        site_id: int,
        deployment_id: int,
        user_id: int,
        metadata: Optional[dict[str, Any]] = None,
    ) -> EdgeDeployment:
        target = (
            await session.exec(
                select(EdgeDeployment).where(
                    and_(
                        EdgeDeployment.id == deployment_id,
                        EdgeDeployment.org_id == org_id,
                        EdgeDeployment.site_id == site_id,
                    )
                )
            )
        ).first()
        if not target:
            raise ValueError("deployment not found")

        active = (
            await session.exec(
                select(EdgeDeployment).where(
                    and_(
                        EdgeDeployment.org_id == org_id,
                        EdgeDeployment.site_id == site_id,
                        EdgeDeployment.channel == target.channel,
                        EdgeDeployment.status == "active",
                    )
                )
            )
        ).all()
        active_id = active[0].id if active else None
        for row in active:
            row.status = "rolled_back"
            row.rolled_back_at = datetime.utcnow()
            session.add(row)

        deployment = EdgeDeployment(
            org_id=org_id,
            site_id=site_id,
            artifact_id=target.artifact_id,
            deployed_by_user_id=user_id,
            channel=target.channel,
            status="active",
            rolled_back_from_deployment_id=active_id,
            metadata_json=json.dumps(metadata or {}, ensure_ascii=True),
            deployed_at=datetime.utcnow(),
        )
        session.add(deployment)
        await session.commit()
        await session.refresh(deployment)
        return deployment

    async def get_artifact(self, session: AsyncSession, org_id: int, artifact_id: int) -> Optional[EdgeArtifact]:
        row = await session.exec(
            select(EdgeArtifact).where(
                and_(
                    EdgeArtifact.org_id == org_id,
                    EdgeArtifact.id == artifact_id,
                )
            )
        )
        return row.first()


edge_service = EdgeService()
