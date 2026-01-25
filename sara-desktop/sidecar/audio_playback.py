"""
Audio Playback Detector

Detects when the system is playing audio so the voice agent
can filter out speaker output from microphone input.

Supports:
- Linux: PulseAudio/PipeWire via pulsectl
- Windows: Windows Audio Session API via pycaw
"""
import asyncio
import logging
import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Try to import pulsectl for Linux
try:
    import pulsectl
    PULSECTL_AVAILABLE = True
except ImportError:
    pulsectl = None
    PULSECTL_AVAILABLE = False

# Try to import pycaw for Windows
try:
    from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume, IAudioMeterInformation
    from comtypes import CLSCTX_ALL
    PYCAW_AVAILABLE = True
except ImportError:
    AudioUtilities = None
    ISimpleAudioVolume = None
    IAudioMeterInformation = None
    PYCAW_AVAILABLE = False


@dataclass
class AudioPlaybackState:
    """Current audio playback state."""
    is_playing: bool = False
    active_streams: int = 0
    volume_level: float = 0.0  # 0.0 to 1.0
    applications: list = None  # List of apps playing audio
    last_updated: datetime = None

    def __post_init__(self):
        if self.applications is None:
            self.applications = []
        if self.last_updated is None:
            self.last_updated = datetime.utcnow()


class AudioPlaybackDetector:
    """
    Monitors system audio playback to inform the voice agent.

    When audio is playing through speakers, the Jetson mic will pick it up.
    By knowing when the PC is playing audio, we can:
    1. Filter out transcriptions during playback
    2. Raise VAD threshold to only capture loud speech
    3. Tag transcriptions as "during_playback" for later filtering
    """

    def __init__(
        self,
        on_state_change: Optional[Callable[[AudioPlaybackState], None]] = None,
        check_interval: float = 1.0
    ):
        self.on_state_change = on_state_change
        self.check_interval = check_interval
        self._running = False
        self._state = AudioPlaybackState()
        self._pulse = None

    @property
    def state(self) -> AudioPlaybackState:
        return self._state

    @property
    def is_available(self) -> bool:
        """Check if audio detection is available on this platform."""
        system = platform.system()
        if system == "Linux":
            return PULSECTL_AVAILABLE
        elif system == "Windows":
            return PYCAW_AVAILABLE
        return False

    async def start(self):
        """Start monitoring audio playback."""
        if not self.is_available:
            logger.warning("Audio playback detection not available on this platform")
            return

        logger.info("Starting audio playback detector")
        self._running = True

        system = platform.system()
        if system == "Linux":
            await self._monitor_pulseaudio()
        elif system == "Windows":
            await self._monitor_windows()

    async def stop(self):
        """Stop monitoring."""
        self._running = False
        if self._pulse:
            self._pulse.close()
            self._pulse = None

    async def _monitor_windows(self):
        """Monitor Windows Audio Session API for active playback streams."""
        try:
            # Get the default speakers device for system-wide audio metering
            speakers = AudioUtilities.GetSpeakers()
            interface = speakers.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None)
            system_meter = interface.QueryInterface(IAudioMeterInformation)

            while self._running:
                try:
                    # Check system-wide audio output level
                    system_peak = system_meter.GetPeakValue() if system_meter else 0
                    is_audio_playing = system_peak > 0.001

                    # Get list of apps with active audio sessions
                    active_streams = []
                    total_volume = 0.0

                    if is_audio_playing:
                        sessions = AudioUtilities.GetAllSessions()
                        for session in sessions:
                            if session.Process:
                                try:
                                    # Check if this session has audio activity
                                    meter = session._ctl.QueryInterface(IAudioMeterInformation)
                                    if meter and meter.GetPeakValue() > 0.001:
                                        active_streams.append(session.Process.name())
                                        # Get volume
                                        try:
                                            vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                                            if vol:
                                                total_volume = max(total_volume, vol.GetMasterVolume())
                                        except Exception:
                                            pass
                                except Exception:
                                    # If we can't get meter, but system is playing, include active sessions
                                    if session.State == 1:  # AudioSessionStateActive
                                        active_streams.append(session.Process.name())

                    # Update state
                    new_state = AudioPlaybackState(
                        is_playing=is_audio_playing,
                        active_streams=len(active_streams),
                        volume_level=max(total_volume, system_peak),
                        applications=active_streams if active_streams else (["System Audio"] if is_audio_playing else []),
                        last_updated=datetime.utcnow()
                    )

                    # Notify on change
                    if new_state.is_playing != self._state.is_playing:
                        logger.info(f"Audio playback {'started' if new_state.is_playing else 'stopped'}: {new_state.applications}")
                        if self.on_state_change:
                            self.on_state_change(new_state)

                    self._state = new_state

                except Exception as e:
                    logger.error(f"Error checking Windows audio playback: {e}")

                await asyncio.sleep(self.check_interval)

        except Exception as e:
            logger.error(f"Failed to initialize Windows audio monitor: {e}")

    async def _monitor_pulseaudio(self):
        """Monitor PulseAudio/PipeWire for active playback streams."""
        try:
            self._pulse = pulsectl.Pulse("sara-audio-monitor")

            while self._running:
                try:
                    # Get all sink inputs (applications playing audio)
                    sink_inputs = self._pulse.sink_input_list()

                    # Filter for actually playing streams
                    active_streams = []
                    total_volume = 0.0

                    for sink in sink_inputs:
                        # Check if the stream is actually playing (not corked/paused)
                        if not sink.corked:
                            app_name = sink.proplist.get('application.name', 'Unknown')
                            volume = sink.volume.value_flat if hasattr(sink.volume, 'value_flat') else 0
                            active_streams.append(app_name)
                            total_volume = max(total_volume, volume)

                    # Update state
                    new_state = AudioPlaybackState(
                        is_playing=len(active_streams) > 0,
                        active_streams=len(active_streams),
                        volume_level=min(total_volume, 1.0),
                        applications=active_streams,
                        last_updated=datetime.utcnow()
                    )

                    # Notify on change
                    if new_state.is_playing != self._state.is_playing:
                        logger.info(f"Audio playback {'started' if new_state.is_playing else 'stopped'}: {active_streams}")
                        if self.on_state_change:
                            self.on_state_change(new_state)

                    self._state = new_state

                except pulsectl.PulseError as e:
                    logger.debug(f"PulseAudio error: {e}")
                except Exception as e:
                    logger.error(f"Error checking audio playback: {e}")

                await asyncio.sleep(self.check_interval)

        except Exception as e:
            logger.error(f"Failed to initialize PulseAudio monitor: {e}")
        finally:
            if self._pulse:
                self._pulse.close()
                self._pulse = None

    def get_state_dict(self) -> dict:
        """Get state as dictionary for API transmission."""
        return {
            "is_playing": self._state.is_playing,
            "active_streams": self._state.active_streams,
            "volume_level": self._state.volume_level,
            "applications": self._state.applications,
            "last_updated": self._state.last_updated.isoformat() if self._state.last_updated else None
        }


# Singleton instance
_audio_detector: Optional[AudioPlaybackDetector] = None


def get_audio_detector() -> AudioPlaybackDetector:
    """Get or create the audio playback detector."""
    global _audio_detector
    if _audio_detector is None:
        _audio_detector = AudioPlaybackDetector()
    return _audio_detector


def is_available() -> bool:
    """Check if audio playback detection is available."""
    return get_audio_detector().is_available
