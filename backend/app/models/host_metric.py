"""
HostMetric — compact numeric time-series extracted from each fleet report.

The full telemetry snapshot lives on ``ManagedHost.agent_snapshot`` (latest only);
this table keeps a small numeric row per report so Sara can reason about trends
("load's been climbing since Tuesday") and the dashboard can draw sparklines.

~288 rows/day/host at the 5-min default interval; a Celery beat prunes rows
older than 30 days. Timestamp is server arrival time (clock-skew immune).
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.db.base import Base


class HostMetric(Base):
    __tablename__ = "host_metric"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    host_id = Column(String, ForeignKey("managed_host.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    ts = Column(DateTime(timezone=True), server_default=func.now(), index=True)  # server arrival

    cpu_pct = Column(Float, nullable=True)
    load1 = Column(Float, nullable=True)
    mem_pct = Column(Float, nullable=True)
    swap_pct = Column(Float, nullable=True)
    disk_max_pct = Column(Float, nullable=True)
    temp_max_c = Column(Float, nullable=True)
    net_rx_bps = Column(Float, nullable=True)
    net_tx_bps = Column(Float, nullable=True)
    failed_units = Column(Integer, nullable=True)

    extras = Column(JSONB, nullable=True)  # anything else worth trending later

    def __repr__(self):
        return f"<HostMetric(host_id={self.host_id}, ts={self.ts}, cpu={self.cpu_pct})>"
