"""Transcript knowledge base: pgvector extension, transcript_chunks and search.

Revision ID: 0002_transcript_chunks
Revises: 0001_initial_schema
Create Date: 2026-09-22

Adds the semantic retrieval foundation described in docs/architecture.md:

* the ``vector`` extension,
* ``transcript_chunks`` with the embedding column and source metadata,
* an HNSW index for cosine similarity search,
* the ``match_transcript_chunks`` SQL function used by retrieval.

The embedding dimension is fixed at 384 to match the selected embedding model
(``BAAI/bge-small-en-v1.5``). Changing the model requires a new migration.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002_transcript_chunks"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Must match backend/app/db/models.py and the selected embedding model.
EMBEDDING_DIMENSION = 384

MATCH_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION match_transcript_chunks(
    query_embedding vector({EMBEDDING_DIMENSION}),
    match_count integer DEFAULT 5,
    match_threshold double precision DEFAULT NULL,
    filter_guest text DEFAULT NULL,
    filter_episode_id text DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    episode_id text,
    guest text,
    title text,
    youtube_url text,
    publish_date date,
    chunk_index integer,
    content text,
    metadata jsonb,
    similarity double precision
)
LANGUAGE sql
STABLE
SET search_path = public, extensions
AS $$
    SELECT
        c.id,
        c.episode_id,
        c.guest,
        c.title,
        c.youtube_url,
        c.publish_date,
        c.chunk_index,
        c.content,
        c.metadata,
        (1 - (c.embedding <=> query_embedding))::double precision AS similarity
    FROM transcript_chunks AS c
    WHERE (match_threshold IS NULL OR (1 - (c.embedding <=> query_embedding)) >= match_threshold)
      AND (filter_guest IS NULL OR c.guest = filter_guest)
      AND (filter_episode_id IS NULL OR c.episode_id = filter_episode_id)
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "transcript_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("episode_id", sa.Text(), nullable=False),
        sa.Column("guest", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("youtube_url", sa.Text(), nullable=True),
        sa.Column("publish_date", sa.Date(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_transcript_chunks"),
        sa.UniqueConstraint("episode_id", "chunk_index", name="uq_transcript_chunks_episode_chunk"),
    )
    op.create_index("ix_transcript_chunks_episode_id", "transcript_chunks", ["episode_id"])
    op.create_index(
        "ix_transcript_chunks_embedding_hnsw",
        "transcript_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )
    # Remove a scrapped prototype overload (it selected a column that never
    # existed). Leaving it in place would make three-argument calls ambiguous.
    op.execute("DROP FUNCTION IF EXISTS match_transcript_chunks(vector, double precision, integer)")
    op.execute(MATCH_FUNCTION_SQL)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS match_transcript_chunks(vector, integer, double precision, text, text)")
    op.drop_index("ix_transcript_chunks_embedding_hnsw", table_name="transcript_chunks")
    op.drop_index("ix_transcript_chunks_episode_id", table_name="transcript_chunks")
    op.drop_table("transcript_chunks")
    # The vector extension is left installed: it is shared database infrastructure.
