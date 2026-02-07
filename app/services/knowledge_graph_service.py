import json
import re
from datetime import datetime
from typing import Any, Optional

from sqlmodel import and_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.innovation_plus import BrandEntity, BrandEntityRelation, SchemaDraft
from app.models.site import Site


class KnowledgeGraphService:
    def _slugify(self, raw: str) -> str:
        lowered = (raw or "").strip().lower()
        lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
        lowered = lowered.strip("-")
        return lowered[:80] if lowered else "entity"

    def parse_dict(self, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    async def list_entities(self, session: AsyncSession, org_id: int, entity_type: Optional[str] = None) -> list[BrandEntity]:
        query = select(BrandEntity).where(BrandEntity.org_id == org_id)
        if entity_type:
            query = query.where(BrandEntity.entity_type == entity_type)
        query = query.order_by(BrandEntity.created_at.desc())
        rows = await session.exec(query)
        return rows.all()

    async def create_entity(
        self,
        session: AsyncSession,
        org_id: int,
        user_id: int,
        entity_type: str,
        name: str,
        description: Optional[str],
        attributes: Optional[dict[str, Any]],
    ) -> BrandEntity:
        etype = (entity_type or "").strip()
        if not etype:
            raise ValueError("entity_type is required")

        entity_name = (name or "").strip()
        if not entity_name:
            raise ValueError("name is required")

        row = BrandEntity(
            org_id=org_id,
            created_by_user_id=user_id,
            entity_type=etype,
            name=entity_name,
            canonical_key=f"{etype.lower()}:{self._slugify(entity_name)}",
            description=(description or "").strip() or None,
            attributes_json=json.dumps(attributes or {}, ensure_ascii=True),
            is_active=True,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def create_relation(
        self,
        session: AsyncSession,
        org_id: int,
        from_entity_id: int,
        to_entity_id: int,
        relation_type: str,
        weight: float = 1.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> BrandEntityRelation:
        from_entity = (
            await session.exec(
                select(BrandEntity).where(
                    and_(
                        BrandEntity.org_id == org_id,
                        BrandEntity.id == from_entity_id,
                    )
                )
            )
        ).first()
        to_entity = (
            await session.exec(
                select(BrandEntity).where(
                    and_(
                        BrandEntity.org_id == org_id,
                        BrandEntity.id == to_entity_id,
                    )
                )
            )
        ).first()
        if not from_entity or not to_entity:
            raise ValueError("Entity not found in this organization")

        relation = BrandEntityRelation(
            org_id=org_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            relation_type=(relation_type or "").strip() or "related_to",
            weight=float(weight),
            metadata_json=json.dumps(metadata or {}, ensure_ascii=True),
        )
        session.add(relation)
        await session.commit()
        await session.refresh(relation)
        return relation

    async def list_relations(self, session: AsyncSession, org_id: int) -> list[BrandEntityRelation]:
        rows = await session.exec(
            select(BrandEntityRelation)
            .where(BrandEntityRelation.org_id == org_id)
            .order_by(BrandEntityRelation.created_at.desc())
        )
        return rows.all()

    def _entity_to_schema_node(self, entity: BrandEntity) -> dict[str, Any]:
        attrs = self.parse_dict(entity.attributes_json)
        node_type = entity.entity_type or "Thing"
        node = {
            "@type": node_type,
            "name": entity.name,
        }
        if entity.description:
            node["description"] = entity.description
        for key, value in attrs.items():
            if key.startswith("_"):
                continue
            node[key] = value
        return node

    async def generate_schema_draft_for_site(
        self,
        session: AsyncSession,
        org_id: int,
        site_id: int,
        user_id: int,
        entity_ids: Optional[list[int]] = None,
    ) -> SchemaDraft:
        site = (
            await session.exec(
                select(Site).where(
                    and_(
                        Site.id == site_id,
                        Site.org_id == org_id,
                    )
                )
            )
        ).first()
        if not site:
            raise ValueError("Site not found")

        query = select(BrandEntity).where(
            and_(
                BrandEntity.org_id == org_id,
                BrandEntity.is_active == True,  # noqa: E712
            )
        )
        if entity_ids:
            query = query.where(BrandEntity.id.in_(entity_ids))
        entities = (await session.exec(query)).all()

        graph = [self._entity_to_schema_node(entity) for entity in entities]
        if not graph:
            graph = [
                {
                    "@type": "WebSite",
                    "name": site.url,
                    "url": site.url,
                }
            ]

        schema = {
            "@context": "https://schema.org",
            "@graph": graph,
        }
        draft = SchemaDraft(
            org_id=org_id,
            site_id=site.id,
            generated_by_user_id=user_id,
            status="draft",
            schema_type="GraphComposite",
            json_ld_content=json.dumps(schema, ensure_ascii=True),
            source_json=json.dumps(
                {
                    "entity_ids": [entity.id for entity in entities if entity.id is not None],
                    "entity_count": len(entities),
                    "generated_at": datetime.utcnow().isoformat(),
                },
                ensure_ascii=True,
            ),
        )
        session.add(draft)
        await session.commit()
        await session.refresh(draft)
        return draft

    async def list_schema_drafts(self, session: AsyncSession, org_id: int, site_id: Optional[int] = None) -> list[SchemaDraft]:
        query = select(SchemaDraft).where(SchemaDraft.org_id == org_id)
        if site_id is not None:
            query = query.where(SchemaDraft.site_id == site_id)
        query = query.order_by(SchemaDraft.created_at.desc())
        rows = await session.exec(query)
        return rows.all()

    async def get_schema_draft(self, session: AsyncSession, org_id: int, draft_id: int) -> Optional[SchemaDraft]:
        row = await session.exec(
            select(SchemaDraft).where(
                and_(
                    SchemaDraft.org_id == org_id,
                    SchemaDraft.id == draft_id,
                )
            )
        )
        return row.first()

    async def apply_schema_draft(
        self,
        session: AsyncSession,
        org_id: int,
        draft_id: int,
        user_id: int,
    ) -> tuple[SchemaDraft, Site]:
        draft = await self.get_schema_draft(session, org_id, draft_id)
        if not draft:
            raise ValueError("Schema draft not found")

        site = (
            await session.exec(
                select(Site).where(
                    and_(
                        Site.org_id == org_id,
                        Site.id == draft.site_id,
                    )
                )
            )
        ).first()
        if not site:
            raise ValueError("Site not found for schema draft")

        site.json_ld_content = draft.json_ld_content
        site.json_ld = draft.json_ld_content
        site.schema_type = draft.schema_type
        site.updated_at = datetime.utcnow()

        draft.status = "applied"
        draft.applied_by_user_id = user_id
        draft.applied_at = datetime.utcnow()
        draft.updated_at = datetime.utcnow()

        session.add(site)
        session.add(draft)
        await session.commit()
        await session.refresh(site)
        await session.refresh(draft)
        return draft, site


knowledge_graph_service = KnowledgeGraphService()
