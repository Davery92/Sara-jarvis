"""
Pagination Utilities

Provides pagination helpers for list endpoints:
- Pagination parameters
- Response models
- SQLAlchemy query pagination
- Cursor-based pagination (for infinite scroll)
"""

from typing import Generic, TypeVar, List, Optional
from pydantic import BaseModel, Field
from fastapi import Query
from sqlalchemy.orm import Query as SQLAlchemyQuery

T = TypeVar('T')


# ==========================================
# PAGINATION MODELS
# ==========================================

class PaginationParams(BaseModel):
    """Standard pagination query parameters"""
    skip: int = Field(0, ge=0, description="Number of items to skip")
    limit: int = Field(50, ge=1, le=100, description="Maximum number of items to return")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response"""
    items: List[T]
    total: int
    skip: int
    limit: int
    has_more: bool

    class Config:
        from_attributes = True


class CursorPaginationParams(BaseModel):
    """Cursor-based pagination for infinite scroll"""
    cursor: Optional[str] = Field(None, description="Cursor for next page")
    limit: int = Field(50, ge=1, le=100, description="Maximum number of items")


class CursorPaginatedResponse(BaseModel, Generic[T]):
    """Cursor-based paginated response"""
    items: List[T]
    next_cursor: Optional[str] = None
    has_more: bool


# ==========================================
# QUERY PARAMETER DEPENDENCIES
# ==========================================

def get_pagination_params(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return")
) -> PaginationParams:
    """Dependency for standard pagination parameters"""
    return PaginationParams(skip=skip, limit=limit)


def get_cursor_pagination_params(
    cursor: Optional[str] = Query(None, description="Cursor for next page"),
    limit: int = Query(50, ge=1, le=100, description="Maximum items to return")
) -> CursorPaginationParams:
    """Dependency for cursor-based pagination parameters"""
    return CursorPaginationParams(cursor=cursor, limit=limit)


# ==========================================
# PAGINATION HELPERS
# ==========================================

def paginate_query(
    query: SQLAlchemyQuery,
    skip: int = 0,
    limit: int = 50
) -> PaginatedResponse:
    """
    Paginate a SQLAlchemy query

    Args:
        query: SQLAlchemy query object
        skip: Number of items to skip
        limit: Maximum items to return

    Returns:
        PaginatedResponse with items and metadata
    """
    # Get total count (can be expensive for large datasets)
    total = query.count()

    # Get paginated items
    items = query.offset(skip).limit(limit).all()

    return PaginatedResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
        has_more=(skip + len(items)) < total
    )


def paginate_list(
    items: List[T],
    skip: int = 0,
    limit: int = 50
) -> PaginatedResponse[T]:
    """
    Paginate a list in memory

    Args:
        items: List to paginate
        skip: Number of items to skip
        limit: Maximum items to return

    Returns:
        PaginatedResponse with items and metadata
    """
    total = len(items)
    paginated_items = items[skip:skip + limit]

    return PaginatedResponse(
        items=paginated_items,
        total=total,
        skip=skip,
        limit=limit,
        has_more=(skip + len(paginated_items)) < total
    )


def encode_cursor(value: str) -> str:
    """Encode a cursor value (base64)"""
    import base64
    return base64.b64encode(value.encode()).decode()


def decode_cursor(cursor: str) -> str:
    """Decode a cursor value (base64)"""
    import base64
    return base64.b64decode(cursor.encode()).decode()


def paginate_with_cursor(
    query: SQLAlchemyQuery,
    cursor_field: str,
    cursor: Optional[str] = None,
    limit: int = 50,
    ascending: bool = True
) -> CursorPaginatedResponse:
    """
    Paginate using cursor-based pagination

    Args:
        query: SQLAlchemy query
        cursor_field: Field name to use for cursor (e.g., 'id', 'created_at')
        cursor: Current cursor value
        limit: Maximum items to return
        ascending: Sort order (True = ASC, False = DESC)

    Returns:
        CursorPaginatedResponse with items and next cursor
    """
    # Apply cursor filter if provided
    if cursor:
        cursor_value = decode_cursor(cursor)
        if ascending:
            query = query.filter(getattr(query.column_descriptions[0]['type'], cursor_field) > cursor_value)
        else:
            query = query.filter(getattr(query.column_descriptions[0]['type'], cursor_field) < cursor_value)

    # Fetch limit + 1 to check if there are more items
    items = query.limit(limit + 1).all()

    has_more = len(items) > limit
    if has_more:
        items = items[:limit]

    # Generate next cursor
    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        cursor_value = str(getattr(last_item, cursor_field))
        next_cursor = encode_cursor(cursor_value)

    return CursorPaginatedResponse(
        items=items,
        next_cursor=next_cursor,
        has_more=has_more
    )


# ==========================================
# EXAMPLE USAGE
# ==========================================

"""
# Standard pagination
@app.get("/notes", response_model=PaginatedResponse[NoteResponse])
async def list_notes(
    pagination: PaginationParams = Depends(get_pagination_params),
    current_user=Depends(get_current_user)
):
    query = db.query(Note).filter(Note.user_id == current_user.id)
    return paginate_query(query, pagination.skip, pagination.limit)


# Cursor-based pagination (infinite scroll)
@app.get("/notes/infinite", response_model=CursorPaginatedResponse[NoteResponse])
async def list_notes_infinite(
    pagination: CursorPaginationParams = Depends(get_cursor_pagination_params),
    current_user=Depends(get_current_user)
):
    query = db.query(Note).filter(Note.user_id == current_user.id).order_by(Note.created_at.desc())
    return paginate_with_cursor(
        query,
        cursor_field='created_at',
        cursor=pagination.cursor,
        limit=pagination.limit,
        ascending=False
    )
"""
