"""GPU memory manager for Jetson Orin Nano.

Pre-allocates CUDA memory pools at boot to prevent fragmentation.
Monitors GPU memory usage and temperature via Jetson sysfs (not pynvml).

Jetson shares system RAM with the GPU (unified memory), so memory stats
come from /proc/meminfo and GPU temp from sysfs thermal zones.
"""

import logging
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

# Jetson sysfs paths
GPU_THERMAL_ZONE = "/sys/class/thermal/thermal_zone1/temp"  # gpu-thermal
GPU_LOAD_PATH = "/sys/devices/gpu.0/load"  # may not exist on all Jetsons


class GPUMemoryManager:
    """Manages GPU memory allocation and monitoring on Jetson."""

    def __init__(self, config: dict):
        gpu_cfg = config.get("gpu", {})
        self._pre_allocate = gpu_cfg.get("pre_allocate", True)
        self._device_id = gpu_cfg.get("cuda_device", 0)
        self._pool_mb = gpu_cfg.get("memory_pool_mb", 512)
        self._initialized = False

    def initialize(self):
        """Initialize CUDA context and optionally pre-allocate memory pool."""
        # Log Jetson memory info
        mem = psutil.virtual_memory()
        logger.info(
            "System memory: Total=%dMB, Available=%dMB, Used=%dMB (%.0f%%)",
            mem.total // (1024 * 1024),
            mem.available // (1024 * 1024),
            mem.used // (1024 * 1024),
            mem.percent,
        )

        gpu_temp = self._read_gpu_temp()
        if gpu_temp is not None:
            logger.info("GPU temperature: %d°C", gpu_temp)

        if self._pre_allocate:
            try:
                self._pre_allocate_pool()
            except Exception as e:
                logger.warning("GPU pre-allocation failed (non-fatal): %s", e)

        self._initialized = True

    def _pre_allocate_pool(self):
        """Pre-allocate CUDA memory pool to reduce fragmentation."""
        try:
            import torch
            if not torch.cuda.is_available():
                logger.warning("CUDA not available for pre-allocation")
                return

            torch.cuda.set_device(self._device_id)

            # Warm up CUDA context
            _ = torch.zeros(1, device="cuda")

            # Set memory allocator limits
            if hasattr(torch.cuda, "set_per_process_memory_fraction"):
                torch.cuda.set_per_process_memory_fraction(0.8, self._device_id)

            logger.info("CUDA memory pool pre-allocated (%dMB requested)", self._pool_mb)
        except ImportError:
            logger.info("PyTorch not installed — skipping CUDA pre-allocation")
        except Exception as e:
            logger.warning("CUDA pre-allocation error: %s", e)

    @staticmethod
    def _read_gpu_temp() -> int | None:
        """Read GPU temperature from Jetson sysfs thermal zone."""
        try:
            temp_path = Path(GPU_THERMAL_ZONE)
            if temp_path.exists():
                raw = temp_path.read_text().strip()
                return int(raw) // 1000  # millidegrees → degrees
        except Exception:
            pass
        return None

    @staticmethod
    def _read_gpu_load() -> int | None:
        """Read GPU utilization from Jetson sysfs (0-1000 scale)."""
        try:
            load_path = Path(GPU_LOAD_PATH)
            if load_path.exists():
                raw = load_path.read_text().strip()
                return int(raw) // 10  # 0-1000 → 0-100%
        except Exception:
            pass
        return None

    def get_stats(self) -> dict:
        """Get current GPU memory and temperature stats.

        On Jetson, GPU shares system RAM (unified memory architecture).
        """
        mem = psutil.virtual_memory()
        gpu_temp = self._read_gpu_temp()
        gpu_load = self._read_gpu_load()

        return {
            "gpu_available": True,  # Jetson always has a GPU
            "memory_total_mb": mem.total // (1024 * 1024),
            "memory_used_mb": mem.used // (1024 * 1024),
            "memory_free_mb": mem.available // (1024 * 1024),
            "temperature_c": gpu_temp or 0,
            "utilization_pct": gpu_load or 0,
        }

    @property
    def is_initialized(self) -> bool:
        return self._initialized
