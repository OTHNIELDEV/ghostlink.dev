import asyncio

from app.services.approval_service import approval_service


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self):
        self.queries = []

    async def exec(self, query):
        self.queries.append(query)
        return _Result([])


async def _build_query_sql(limit=None, status=None) -> str:
    session = _Session()
    await approval_service.list_requests(
        session=session,
        org_id=1,
        status=status,
        limit=limit,
    )
    return str(session.queries[0])


def test_list_requests_accepts_limit():
    sql = asyncio.run(_build_query_sql(limit=5))
    assert "LIMIT" in sql


def test_list_requests_omits_limit_when_not_provided():
    sql = asyncio.run(_build_query_sql())
    assert "LIMIT" not in sql
