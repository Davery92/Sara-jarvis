"""
System Metrics Collection for Sara Headless Agent

Collects CPU, RAM, disk, network, and optional GPU metrics.
"""
import logging
import os
import platform
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available - metrics will be limited")

# Try to import GPU monitoring
try:
    import pynvml
    pynvml.nvmlInit()
    NVIDIA_AVAILABLE = True
except Exception:
    NVIDIA_AVAILABLE = False


@dataclass
class CPUMetrics:
    usage_percent: float
    core_count: int
    frequency_mhz: Optional[float] = None
    per_core_usage: Optional[List[float]] = None
    load_avg_1m: Optional[float] = None
    load_avg_5m: Optional[float] = None
    load_avg_15m: Optional[float] = None


@dataclass
class MemoryMetrics:
    total_gb: float
    available_gb: float
    used_gb: float
    percent_used: float
    swap_total_gb: Optional[float] = None
    swap_used_gb: Optional[float] = None
    swap_percent: Optional[float] = None


@dataclass
class DiskMetrics:
    mount_point: str
    device: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent_used: float
    filesystem: str


@dataclass
class NetworkMetrics:
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    errors_in: int
    errors_out: int


@dataclass
class GPUMetrics:
    index: int
    name: str
    memory_total_mb: int
    memory_used_mb: int
    memory_free_mb: int
    utilization_percent: int
    temperature_c: Optional[int] = None
    power_draw_w: Optional[float] = None


@dataclass
class SystemMetrics:
    timestamp: str
    hostname: str
    platform: str
    uptime_seconds: float
    cpu: CPUMetrics
    memory: MemoryMetrics
    disks: List[DiskMetrics]
    network: NetworkMetrics
    gpus: Optional[List[GPUMetrics]] = None
    temperatures: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class MetricsCollector:
    """Collects system metrics from the host."""

    def __init__(self):
        self._last_net_io = None
        self._last_net_time = None

    def collect(self) -> Optional[SystemMetrics]:
        """Collect all system metrics."""
        if not PSUTIL_AVAILABLE:
            logger.warning("psutil not available, cannot collect metrics")
            return None

        try:
            from datetime import datetime, timezone

            return SystemMetrics(
                timestamp=datetime.now(timezone.utc).isoformat(),
                hostname=platform.node(),
                platform=platform.system().lower(),
                uptime_seconds=self._get_uptime(),
                cpu=self._collect_cpu(),
                memory=self._collect_memory(),
                disks=self._collect_disks(),
                network=self._collect_network(),
                gpus=self._collect_gpus() if NVIDIA_AVAILABLE else None,
                temperatures=self._collect_temperatures(),
            )
        except Exception as e:
            logger.error(f"Failed to collect metrics: {e}")
            return None

    def _get_uptime(self) -> float:
        """Get system uptime in seconds."""
        import time
        return time.time() - psutil.boot_time()

    def _collect_cpu(self) -> CPUMetrics:
        """Collect CPU metrics."""
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_freq = psutil.cpu_freq()
        per_core = psutil.cpu_percent(percpu=True)

        # Load average (Unix only)
        load_avg = None
        if hasattr(os, 'getloadavg'):
            load_avg = os.getloadavg()

        return CPUMetrics(
            usage_percent=cpu_percent,
            core_count=psutil.cpu_count(logical=True),
            frequency_mhz=cpu_freq.current if cpu_freq else None,
            per_core_usage=per_core,
            load_avg_1m=load_avg[0] if load_avg else None,
            load_avg_5m=load_avg[1] if load_avg else None,
            load_avg_15m=load_avg[2] if load_avg else None,
        )

    def _collect_memory(self) -> MemoryMetrics:
        """Collect memory metrics."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return MemoryMetrics(
            total_gb=round(mem.total / (1024**3), 2),
            available_gb=round(mem.available / (1024**3), 2),
            used_gb=round(mem.used / (1024**3), 2),
            percent_used=mem.percent,
            swap_total_gb=round(swap.total / (1024**3), 2) if swap.total > 0 else None,
            swap_used_gb=round(swap.used / (1024**3), 2) if swap.total > 0 else None,
            swap_percent=swap.percent if swap.total > 0 else None,
        )

    def _collect_disks(self) -> List[DiskMetrics]:
        """Collect disk metrics for all mounted partitions."""
        disks = []

        for partition in psutil.disk_partitions(all=False):
            try:
                # Skip special filesystems
                if partition.fstype in ('squashfs', 'tmpfs', 'devtmpfs', 'overlay'):
                    continue

                usage = psutil.disk_usage(partition.mountpoint)

                disks.append(DiskMetrics(
                    mount_point=partition.mountpoint,
                    device=partition.device,
                    total_gb=round(usage.total / (1024**3), 2),
                    used_gb=round(usage.used / (1024**3), 2),
                    free_gb=round(usage.free / (1024**3), 2),
                    percent_used=usage.percent,
                    filesystem=partition.fstype,
                ))
            except (PermissionError, OSError):
                continue

        return disks

    def _collect_network(self) -> NetworkMetrics:
        """Collect network I/O metrics."""
        net_io = psutil.net_io_counters()

        return NetworkMetrics(
            bytes_sent=net_io.bytes_sent,
            bytes_recv=net_io.bytes_recv,
            packets_sent=net_io.packets_sent,
            packets_recv=net_io.packets_recv,
            errors_in=net_io.errin,
            errors_out=net_io.errout,
        )

    def _collect_gpus(self) -> Optional[List[GPUMetrics]]:
        """Collect NVIDIA GPU metrics if available."""
        if not NVIDIA_AVAILABLE:
            return None

        gpus = []
        try:
            device_count = pynvml.nvmlDeviceGetCount()

            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode('utf-8')

                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)

                # Temperature (may not be available on all GPUs)
                try:
                    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                except Exception:
                    temp = None

                # Power draw (may not be available)
                try:
                    power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # Convert mW to W
                except Exception:
                    power = None

                gpus.append(GPUMetrics(
                    index=i,
                    name=name,
                    memory_total_mb=memory.total // (1024**2),
                    memory_used_mb=memory.used // (1024**2),
                    memory_free_mb=memory.free // (1024**2),
                    utilization_percent=utilization.gpu,
                    temperature_c=temp,
                    power_draw_w=power,
                ))
        except Exception as e:
            logger.error(f"Failed to collect GPU metrics: {e}")
            return None

        return gpus if gpus else None

    def _collect_temperatures(self) -> Optional[Dict[str, float]]:
        """Collect temperature sensors if available."""
        if not hasattr(psutil, 'sensors_temperatures'):
            return None

        temps = {}
        try:
            sensors = psutil.sensors_temperatures()
            for name, entries in sensors.items():
                for entry in entries:
                    label = entry.label or name
                    key = f"{name}_{label}".replace(' ', '_').lower()
                    temps[key] = entry.current
        except Exception:
            pass

        return temps if temps else None


# Global collector instance
metrics_collector = MetricsCollector()
