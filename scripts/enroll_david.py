#!/usr/bin/env python3
"""
Enroll David for speaker recognition.

Usage:
    python scripts/enroll_david.py sample1.wav sample2.wav sample3.wav

This script enrolls David's voice with the NeMo speaker recognition system
so Sara can identify when David is speaking.

Requirements:
- 1-5 audio samples of David speaking (WAV, MP3, FLAC)
- Each sample should be 5-30 seconds of clear speech
- Varied samples (different phrases, times) improve recognition

The samples are sent to the GPU cluster's speaker enrollment service.
"""

import sys
import os
import asyncio
import argparse
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


async def enroll_david(audio_paths: list, display_name: str = "David"):
    """Enroll David with the given audio samples."""
    from app.services.audio.speaker_service import get_speaker_service

    # Validate paths
    for path in audio_paths:
        if not Path(path).exists():
            print(f"Error: Audio file not found: {path}")
            sys.exit(1)

        # Check file size (should be reasonable)
        size = Path(path).stat().st_size
        if size < 1000:
            print(f"Warning: {path} seems very small ({size} bytes)")
        if size > 50_000_000:
            print(f"Warning: {path} is very large ({size/1_000_000:.1f} MB)")

    print(f"Enrolling David with {len(audio_paths)} audio sample(s)...")
    print(f"Samples: {', '.join(audio_paths)}")

    try:
        speaker_service = await get_speaker_service()

        # Check if already enrolled
        existing = await speaker_service.get_speaker("david")
        if existing:
            print(f"David is already enrolled with {existing.num_samples} samples.")
            response = input("Do you want to re-enroll? (y/N): ")
            if response.lower() != 'y':
                print("Enrollment cancelled.")
                return

            # Delete existing enrollment
            await speaker_service.delete_speaker("david")
            print("Existing enrollment deleted.")

        # Enroll
        result = await speaker_service.enroll_david(audio_paths)

        print("\nEnrollment successful!")
        print(f"  Speaker ID: {result.get('speaker_id', 'david')}")
        print(f"  Samples used: {result.get('num_samples', len(audio_paths))}")

        # Verify enrollment
        print("\nVerifying enrollment...")
        is_enrolled = await speaker_service.is_david_enrolled()
        if is_enrolled:
            print("✓ David is now enrolled and ready for recognition.")
        else:
            print("✗ Warning: Enrollment verification failed.")

    except Exception as e:
        print(f"Error during enrollment: {e}")
        sys.exit(1)


async def check_status():
    """Check David's enrollment status."""
    from app.services.audio.speaker_service import get_speaker_service

    try:
        speaker_service = await get_speaker_service()

        # Check health first
        health = await speaker_service.check_health()
        print(f"Enrollment service: {health.get('status', 'unknown')}")

        # Check David
        speaker = await speaker_service.get_speaker("david")
        if speaker:
            print(f"\nDavid is enrolled:")
            print(f"  Display name: {speaker.display_name}")
            print(f"  Samples: {speaker.num_samples}")
        else:
            print("\nDavid is NOT enrolled.")
            print("Run: python scripts/enroll_david.py sample1.wav sample2.wav sample3.wav")

    except Exception as e:
        print(f"Error checking status: {e}")
        sys.exit(1)


async def list_speakers():
    """List all enrolled speakers."""
    from app.services.audio.speaker_service import get_speaker_service

    try:
        speaker_service = await get_speaker_service()
        speakers = await speaker_service.list_speakers()

        if not speakers:
            print("No speakers enrolled.")
            return

        print(f"Enrolled speakers ({len(speakers)}):")
        for s in speakers:
            print(f"  - {s.speaker_id} ({s.display_name}): {s.num_samples} samples")

    except Exception as e:
        print(f"Error listing speakers: {e}")
        sys.exit(1)


async def add_sample(audio_path: str):
    """Add an additional sample to David's enrollment."""
    from app.services.audio.speaker_service import get_speaker_service

    if not Path(audio_path).exists():
        print(f"Error: Audio file not found: {audio_path}")
        sys.exit(1)

    try:
        speaker_service = await get_speaker_service()

        # Check David is enrolled
        speaker = await speaker_service.get_speaker("david")
        if not speaker:
            print("Error: David is not enrolled. Run full enrollment first.")
            sys.exit(1)

        print(f"Adding sample to David's enrollment: {audio_path}")
        result = await speaker_service.add_sample("david", audio_path)

        print(f"Sample added! David now has {result.get('num_samples', '?')} samples.")

    except Exception as e:
        print(f"Error adding sample: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Enroll David for speaker recognition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Enroll with audio samples
  python scripts/enroll_david.py samples/david1.wav samples/david2.wav samples/david3.wav

  # Check enrollment status
  python scripts/enroll_david.py --status

  # List all enrolled speakers
  python scripts/enroll_david.py --list

  # Add additional sample
  python scripts/enroll_david.py --add-sample samples/david4.wav
        """
    )

    parser.add_argument(
        "audio_files",
        nargs="*",
        help="Audio files for enrollment (1-5 WAV/MP3/FLAC files)"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check David's enrollment status"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all enrolled speakers"
    )
    parser.add_argument(
        "--add-sample",
        metavar="FILE",
        help="Add an additional sample to existing enrollment"
    )
    parser.add_argument(
        "--name",
        default="David",
        help="Display name (default: David)"
    )

    args = parser.parse_args()

    if args.status:
        asyncio.run(check_status())
    elif args.list:
        asyncio.run(list_speakers())
    elif args.add_sample:
        asyncio.run(add_sample(args.add_sample))
    elif args.audio_files:
        if len(args.audio_files) < 1:
            parser.error("At least 1 audio file required")
        if len(args.audio_files) > 5:
            parser.error("Maximum 5 audio files allowed")
        asyncio.run(enroll_david(args.audio_files, args.name))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
