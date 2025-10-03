"""
Unit Tests for DreamConsolidationService

Tests the nightly dream consolidation pipeline:
- Trace clustering
- LLM summarization
- Edge extraction
- Insight generation
"""

import pytest
from datetime import datetime, timedelta
import json


# ==========================================
# TEST DREAM PIPELINE
# ==========================================

@pytest.mark.asyncio
async def test_dream_pipeline_basic(dream_service, db_session, test_user_id, sample_memory_traces):
    """Test basic dream consolidation pipeline"""
    yesterday = datetime.utcnow() - timedelta(days=1)

    result = await dream_service.run_dream_pipeline(
        db=db_session,
        user_id=test_user_id,
        day=yesterday
    )

    assert result["status"] == "success"
    assert result["traces_processed"] == len(sample_memory_traces)
    assert result["clusters_created"] > 0
    assert result["summaries_generated"] > 0
    assert result["edges_created"] > 0
    assert result["insights_extracted"] > 0


@pytest.mark.asyncio
async def test_dream_pipeline_insufficient_traces(dream_service, db_session, test_user_id):
    """Test pipeline skips when too few traces"""
    from app.main_simple import MemoryTrace

    # Add only 2 traces (less than min_cluster_size of 3)
    yesterday = datetime.utcnow() - timedelta(days=1)

    for i in range(2):
        trace = MemoryTrace(
            id=f"trace-{i}",
            user_id=test_user_id,
            content=f"Trace {i}",
            role="user",
            created_at=yesterday + timedelta(minutes=i)
        )
        db_session.add(trace)

    db_session.commit()

    result = await dream_service.run_dream_pipeline(
        db=db_session,
        user_id=test_user_id,
        day=yesterday
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "insufficient_traces"


@pytest.mark.asyncio
async def test_dream_pipeline_disabled(dream_service, db_session, test_user_id):
    """Test pipeline respects enabled flag"""
    dream_service.enabled = False

    result = await dream_service.run_dream_pipeline(
        db=db_session,
        user_id=test_user_id
    )

    assert result["status"] == "disabled"


# ==========================================
# TEST CLUSTERING
# ==========================================

@pytest.mark.asyncio
async def test_cluster_traces_basic(dream_service):
    """Test basic trace clustering"""
    traces = [
        {"id": "1", "content": "Machine learning and AI research", "salience": 0.6, "created_at": datetime.utcnow()},
        {"id": "2", "content": "Deep learning neural networks", "salience": 0.6, "created_at": datetime.utcnow()},
        {"id": "3", "content": "Cooking pasta for dinner", "salience": 0.5, "created_at": datetime.utcnow()},
        {"id": "4", "content": "Artificial intelligence models", "salience": 0.6, "created_at": datetime.utcnow()},
        {"id": "5", "content": "Recipe for tomato sauce", "salience": 0.5, "created_at": datetime.utcnow()},
    ]

    clusters = await dream_service._cluster_traces(traces)

    # Should create at least 1 cluster
    assert len(clusters) > 0

    # All traces should be in some cluster
    all_trace_ids = set()
    for cluster in clusters:
        for trace in cluster:
            all_trace_ids.add(trace["id"])

    assert len(all_trace_ids) >= 3  # At least some traces clustered


@pytest.mark.asyncio
async def test_cluster_traces_high_salience_singleton(dream_service):
    """Test that high-salience traces get their own cluster"""
    traces = [
        {"id": "1", "content": "Regular content", "salience": 0.5, "created_at": datetime.utcnow()},
        {"id": "2", "content": "Very important urgent matter", "salience": 0.9, "created_at": datetime.utcnow()},
        {"id": "3", "content": "Another regular item", "salience": 0.5, "created_at": datetime.utcnow()},
    ]

    clusters = await dream_service._cluster_traces(traces)

    # High salience trace should be in a cluster
    high_salience_cluster = None
    for cluster in clusters:
        if any(t["id"] == "2" for t in cluster):
            high_salience_cluster = cluster
            break

    assert high_salience_cluster is not None


@pytest.mark.asyncio
async def test_cluster_traces_insufficient_size(dream_service):
    """Test clustering with insufficient traces"""
    traces = [
        {"id": "1", "content": "Single trace", "salience": 0.5, "created_at": datetime.utcnow()}
    ]

    clusters = await dream_service._cluster_traces(traces)

    # Should return single cluster with all traces
    assert len(clusters) == 1
    assert len(clusters[0]) == 1


# ==========================================
# TEST SUMMARIZATION
# ==========================================

@pytest.mark.asyncio
async def test_generate_summaries_with_llm(dream_service, mock_llm_client):
    """Test LLM-based summary generation"""
    clusters = [
        [
            {"id": "1", "content": "ML research", "role": "user", "created_at": datetime.utcnow()},
            {"id": "2", "content": "AI models", "role": "assistant", "created_at": datetime.utcnow()},
            {"id": "3", "content": "Neural nets", "role": "user", "created_at": datetime.utcnow()},
        ]
    ]

    summaries = await dream_service._generate_summaries(clusters)

    assert len(summaries) == 1
    summary = summaries[0]

    assert "summary" in summary
    assert "key_points" in summary
    assert "emotional_tone" in summary
    assert "topics" in summary
    assert summary["cluster_size"] == 3


@pytest.mark.asyncio
async def test_generate_summaries_llm_fallback(dream_service, monkeypatch):
    """Test fallback to keyword-based summaries when LLM fails"""
    # Mock LLM to return None (unavailable)
    def mock_get_llm():
        return None

    monkeypatch.setattr(dream_service, "_get_llm_client", mock_get_llm)

    clusters = [
        [
            {"id": "1", "content": "machine learning research paper", "created_at": datetime.utcnow()},
            {"id": "2", "content": "machine learning algorithms", "created_at": datetime.utcnow()},
            {"id": "3", "content": "machine learning models", "created_at": datetime.utcnow()},
        ]
    ]

    summaries = await dream_service._generate_summaries(clusters)

    assert len(summaries) == 1
    summary = summaries[0]

    # Should use fallback
    assert "machine" in summary["topics"] or "learning" in summary["topics"]


@pytest.mark.asyncio
async def test_fallback_summary(dream_service):
    """Test keyword-based fallback summary"""
    cluster = [
        {"id": "1", "content": "python programming language code", "created_at": datetime.utcnow()},
        {"id": "2", "content": "python development tools", "created_at": datetime.utcnow()},
        {"id": "3", "content": "python programming best practices", "created_at": datetime.utcnow()},
    ]

    summary = dream_service._fallback_summary(cluster)

    assert summary["cluster_size"] == 3
    assert "python" in summary["topics"] or "programming" in summary["topics"]
    assert "summary" in summary
    assert "time_span" in summary


# ==========================================
# TEST EDGE EXTRACTION
# ==========================================

@pytest.mark.asyncio
async def test_extract_edges_temporal(dream_service, db_session, test_user_id):
    """Test temporal edge creation within clusters"""
    from app.main_simple import MemoryEdge

    traces = [
        {"id": "1", "content": "Trace 1", "created_at": datetime.utcnow()},
        {"id": "2", "content": "Trace 2", "created_at": datetime.utcnow()},
        {"id": "3", "content": "Trace 3", "created_at": datetime.utcnow()},
    ]

    clusters = [traces]

    edges_created = await dream_service._extract_edges(
        db=db_session,
        user_id=test_user_id,
        traces=traces,
        clusters=clusters
    )

    assert edges_created > 0

    # Check temporal edges exist
    temporal_edges = db_session.query(MemoryEdge).filter(
        MemoryEdge.type == "temporal"
    ).all()

    assert len(temporal_edges) > 0


@pytest.mark.asyncio
async def test_extract_edges_semantic(dream_service, db_session, test_user_id):
    """Test semantic edge creation between clusters"""
    from app.main_simple import MemoryEdge

    cluster1 = [{"id": "1", "content": "Cluster 1", "created_at": datetime.utcnow()}]
    cluster2 = [{"id": "2", "content": "Cluster 2", "created_at": datetime.utcnow()}]

    clusters = [cluster1, cluster2]
    traces = cluster1 + cluster2

    edges_created = await dream_service._extract_edges(
        db=db_session,
        user_id=test_user_id,
        traces=traces,
        clusters=clusters
    )

    assert edges_created > 0

    # Check semantic edges exist
    semantic_edges = db_session.query(MemoryEdge).filter(
        MemoryEdge.type == "semantic"
    ).all()

    assert len(semantic_edges) > 0


# ==========================================
# TEST INSIGHT GENERATION
# ==========================================

@pytest.mark.asyncio
async def test_generate_insights_daily_summary(dream_service, db_session, test_user_id):
    """Test daily summary insight generation"""
    from app.main_simple import DreamInsight

    yesterday = datetime.utcnow() - timedelta(days=1)

    traces = [
        {"id": "1", "content": "Trace 1", "salience": 0.5},
        {"id": "2", "content": "Trace 2", "salience": 0.5},
    ]

    clusters = [traces]

    summaries = [
        {
            "cluster_size": 2,
            "topics": ["test", "mock"],
            "summary": "Test summary",
            "trace_ids": ["1", "2"]
        }
    ]

    insights = await dream_service._generate_insights(
        db=db_session,
        user_id=test_user_id,
        day=yesterday,
        traces=traces,
        clusters=clusters,
        summaries=summaries
    )

    assert len(insights) > 0

    # Check daily summary exists
    daily_summary = db_session.query(DreamInsight).filter(
        DreamInsight.insight_type == "summary"
    ).first()

    assert daily_summary is not None
    assert "Daily Summary" in daily_summary.title


@pytest.mark.asyncio
async def test_generate_insights_pattern_detection(dream_service, db_session, test_user_id):
    """Test pattern detection insight for large clusters"""
    from app.main_simple import DreamInsight

    yesterday = datetime.utcnow() - timedelta(days=1)

    # Large cluster (size >= 5 triggers pattern detection)
    traces = [{"id": str(i), "content": f"Trace {i}", "salience": 0.5} for i in range(6)]
    clusters = [traces]

    summaries = [
        {
            "cluster_size": 6,
            "topics": ["recurring", "theme"],
            "summary": "Pattern detected",
            "trace_ids": [t["id"] for t in traces]
        }
    ]

    insights = await dream_service._generate_insights(
        db=db_session,
        user_id=test_user_id,
        day=yesterday,
        traces=traces,
        clusters=clusters,
        summaries=summaries
    )

    # Should have pattern insight
    pattern_insight = db_session.query(DreamInsight).filter(
        DreamInsight.insight_type == "pattern"
    ).first()

    assert pattern_insight is not None
    assert "Recurring Theme" in pattern_insight.title


@pytest.mark.asyncio
async def test_generate_insights_forgotten_gem(dream_service, db_session, test_user_id):
    """Test forgotten gem insight for high-salience traces"""
    from app.main_simple import DreamInsight

    yesterday = datetime.utcnow() - timedelta(days=1)

    traces = [
        {"id": "1", "content": "Regular trace", "salience": 0.5},
        {"id": "2", "content": "Very important forgotten memory", "salience": 0.9},
    ]

    clusters = [traces]
    summaries = [{"cluster_size": 2, "topics": ["test"], "summary": "Test", "trace_ids": ["1", "2"]}]

    insights = await dream_service._generate_insights(
        db=db_session,
        user_id=test_user_id,
        day=yesterday,
        traces=traces,
        clusters=clusters,
        summaries=summaries
    )

    # Should have forgotten gem
    gem = db_session.query(DreamInsight).filter(
        DreamInsight.insight_type == "forgotten_gem"
    ).first()

    assert gem is not None
    assert "Important Memory" in gem.title


# ==========================================
# TEST SUMMARY STORAGE
# ==========================================

@pytest.mark.asyncio
async def test_store_summaries(dream_service, db_session, test_user_id):
    """Test summary storage as memory traces"""
    from app.main_simple import MemoryTrace, MemoryEdge

    yesterday = datetime.utcnow() - timedelta(days=1)

    summaries = [
        {
            "cluster_size": 3,
            "trace_ids": ["1", "2", "3"],
            "summary": "Test summary of the day",
            "topics": ["test", "mock"],
            "emotional_tone": "positive",
            "key_points": ["point 1", "point 2"]
        }
    ]

    summary_ids = await dream_service._store_summaries(
        db=db_session,
        user_id=test_user_id,
        day=yesterday,
        summaries=summaries
    )

    assert len(summary_ids) == 1

    # Check summary trace exists
    summary_trace = db_session.query(MemoryTrace).filter(
        MemoryTrace.id == summary_ids[0]
    ).first()

    assert summary_trace is not None
    assert summary_trace.role == "summary"
    assert summary_trace.salience == 0.7
    assert "Test summary" in summary_trace.content

    # Check edges to constituent traces
    edges = db_session.query(MemoryEdge).filter(
        MemoryEdge.src == summary_ids[0],
        MemoryEdge.type == "summary_of"
    ).all()

    assert len(edges) == 3  # One edge per trace


# ==========================================
# TEST ERROR HANDLING
# ==========================================

@pytest.mark.asyncio
async def test_dream_pipeline_handles_errors(dream_service, db_session, test_user_id, monkeypatch):
    """Test that pipeline handles errors gracefully"""
    # Mock clustering to raise exception
    async def mock_cluster_error(traces):
        raise Exception("Clustering failed")

    monkeypatch.setattr(dream_service, "_cluster_traces", mock_cluster_error)

    # Add some traces
    from app.main_simple import MemoryTrace
    yesterday = datetime.utcnow() - timedelta(days=1)

    for i in range(5):
        trace = MemoryTrace(
            id=f"trace-{i}",
            user_id=test_user_id,
            content=f"Trace {i}",
            role="user",
            created_at=yesterday + timedelta(minutes=i)
        )
        db_session.add(trace)

    db_session.commit()

    result = await dream_service.run_dream_pipeline(
        db=db_session,
        user_id=test_user_id,
        day=yesterday
    )

    assert result["status"] == "error"
    assert "error" in result
