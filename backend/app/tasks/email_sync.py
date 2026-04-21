"""
Email sync Celery tasks for Microsoft Graph integration.

Handles:
- Periodic email sync from configured mailboxes
- Email analysis (categorization, summarization, importance scoring)
- Attachment processing and RiskNinja detection
- Push notification triggers for important emails
- Calendar invite detection and automatic event creation
"""

import logging
import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from html import unescape
from zoneinfo import ZoneInfo

# User's timezone for calendar events
USER_TIMEZONE = ZoneInfo("America/New_York")

from app.celery_app import celery_app
from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)


def strip_html_tags(html: str) -> str:
    """Convert HTML to plain text."""
    if not html:
        return ""
    # Remove script and style elements
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Replace common block elements with newlines
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</(p|div|tr|li|h[1-6])>', '\n', html, flags=re.IGNORECASE)
    # Remove all remaining tags
    html = re.sub(r'<[^>]+>', '', html)
    # Decode HTML entities
    html = unescape(html)
    # Clean up whitespace
    html = re.sub(r'\n\s*\n+', '\n\n', html)
    return html.strip()


@celery_app.task(
    name="app.tasks.email_sync.sync_emails",
    bind=True,
    queue="cognitive",
    max_retries=2
)
def sync_emails(self):
    """
    Periodic email sync task.
    Fetches new emails from all configured mailboxes.

    Runs every 3 minutes via beat schedule.
    """
    logger.info("Starting email sync")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _sync_emails_async()
        )
        logger.info(f"Email sync complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_sync_emails_async())
        logger.info(f"Email sync complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Email sync failed: {e}")
        raise self.retry(countdown=60, exc=e)


async def _sync_emails_async():
    """Async implementation of email sync."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select, update

    from app.services.msgraph_service import get_msgraph_service, is_riskninja_relevant
    from app.models.email import Email, EmailAttachment, EmailSyncState
    from app.core.config import settings

    database_url = os.getenv("DATABASE_URL", "")

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        msgraph = get_msgraph_service()

        # Default user ID for solo user (configured in SOLO_USER_ID env var)
        user_id = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")

        total_synced = 0
        total_errors = 0
        total_read_updated = 0

        async with async_session() as db:
            for mailbox in settings.msgraph_mailboxes:
                try:
                    # Get last sync timestamp for this mailbox
                    result = await db.execute(
                        select(EmailSyncState).where(
                            EmailSyncState.user_id == user_id,
                            EmailSyncState.mailbox == mailbox
                        )
                    )
                    sync_state = result.scalar_one_or_none()

                    # Get the most recent email received_at for this mailbox
                    # This is more reliable than using last_sync_at timestamp
                    from sqlalchemy import func as sql_func
                    max_received_result = await db.execute(
                        select(sql_func.max(Email.received_at)).where(
                            Email.mailbox == mailbox,
                            Email.user_id == user_id
                        )
                    )
                    max_received_at = max_received_result.scalar_one_or_none()

                    if max_received_at:
                        # Fetch emails newer than our most recent one
                        # Subtract 1 minute to handle any edge cases
                        since = max_received_at - timedelta(minutes=1)
                    elif sync_state and sync_state.last_sync_at:
                        # Fallback to sync state if no emails yet
                        since = sync_state.last_sync_at
                    else:
                        # First sync - get last 24 hours
                        since = local_now() - timedelta(hours=24)

                    logger.info(f"Syncing {mailbox} since {since} (max_received_at: {max_received_at})")

                    # Fetch emails from Graph API
                    emails = await msgraph.get_emails(mailbox, since=since, top=50)

                    synced_count = 0
                    read_status_updated = 0
                    for email_data in emails:
                        try:
                            # Check if email already exists
                            existing = await db.execute(
                                select(Email).where(Email.id == email_data.id)
                            )
                            existing_email = existing.scalar_one_or_none()
                            if existing_email:
                                # Sync read status from Graph API to local DB
                                if existing_email.is_read != email_data.is_read:
                                    existing_email.is_read = email_data.is_read
                                    read_status_updated += 1
                                    logger.debug(f"Updated read status for {email_data.id}: {email_data.is_read}")
                                continue  # Skip full sync for existing emails

                            # Convert HTML body to plain text if needed
                            if email_data.body_content_type == "html":
                                body_text = strip_html_tags(email_data.body_content)
                                body_html = email_data.body_content
                            else:
                                body_text = email_data.body_content
                                body_html = None

                            # Create Email record
                            email = Email(
                                id=email_data.id,
                                user_id=user_id,
                                mailbox=mailbox,
                                conversation_id=email_data.conversation_id,
                                subject=email_data.subject,
                                sender_email=email_data.sender_email,
                                sender_name=email_data.sender_name,
                                received_at=email_data.received_at,
                                importance=email_data.importance,
                                is_read=email_data.is_read,
                                internet_message_id=email_data.internet_message_id,
                                parent_folder_id=email_data.parent_folder_id,
                                body_preview=email_data.body_preview,
                                body_text=body_text,
                                body_html=body_html,
                                to_recipients=email_data.to_recipients,
                                cc_recipients=email_data.cc_recipients,
                            )
                            db.add(email)

                            # Fetch, store, and download attachments if present
                            if email_data.has_attachments:
                                from minio import Minio
                                from io import BytesIO

                                # Initialize MinIO client
                                minio_url = settings.minio_url.replace("http://", "").replace("https://", "")
                                minio_client = Minio(
                                    minio_url,
                                    access_key=settings.minio_access_key,
                                    secret_key=settings.minio_secret_key,
                                    secure=False
                                )

                                attachments = await msgraph.get_attachments(mailbox, email_data.id)
                                for att in attachments:
                                    # Detect RiskNinja relevance
                                    is_rn = is_riskninja_relevant(
                                        att.name,
                                        email_data.subject,
                                        body_text[:1000] if body_text else ""
                                    )

                                    # Determine bucket based on RiskNinja relevance
                                    bucket = "riskninja-docs" if is_rn else settings.minio_bucket

                                    # Ensure bucket exists
                                    if not minio_client.bucket_exists(bucket):
                                        minio_client.make_bucket(bucket)

                                    # Download attachment content immediately
                                    minio_key = None
                                    downloaded_at = None
                                    try:
                                        content = await msgraph.download_attachment(
                                            mailbox, email_data.id, att.id
                                        )
                                        if content:
                                            # Generate storage key
                                            date_prefix = local_now().strftime("%Y/%m/%d")
                                            minio_key = f"email-attachments/{date_prefix}/{email_data.id}/{att.name}"

                                            # Upload to MinIO
                                            minio_client.put_object(
                                                bucket,
                                                minio_key,
                                                BytesIO(content),
                                                length=len(content),
                                                content_type=att.content_type or "application/octet-stream"
                                            )
                                            downloaded_at = local_now()
                                            logger.info(f"Downloaded attachment: {att.name} -> {bucket}/{minio_key}")
                                    except Exception as e:
                                        logger.warning(f"Failed to download attachment {att.name}: {e}")

                                    attachment = EmailAttachment(
                                        id=att.id,
                                        email_id=email_data.id,
                                        filename=att.name,
                                        content_type=att.content_type,
                                        size=att.size,
                                        is_inline=att.is_inline,
                                        content_id=att.content_id,
                                        is_riskninja_relevant=is_rn,
                                        minio_bucket=bucket if minio_key else None,
                                        minio_key=minio_key,
                                        downloaded_at=downloaded_at
                                    )
                                    db.add(attachment)

                            synced_count += 1

                        except Exception as e:
                            logger.error(f"Failed to sync email {email_data.id}: {e}")
                            total_errors += 1
                            continue

                    # --- Read-status reconciliation ---
                    # The main sync only fetches emails newer than max_received_at,
                    # so it misses read-status changes on older emails. This pass
                    # fetches recent messages (last 3 days) with just id+isRead and
                    # reconciles against locally-unread emails.
                    try:
                        reconcile_since = local_now() - timedelta(days=3)
                        read_check_emails = await msgraph.get_emails(
                            mailbox, since=reconcile_since, top=100,
                            select_fields=["id", "isRead"]
                        )
                        # Build a map of graph_id -> is_read
                        graph_read_map = {e.id: e.is_read for e in read_check_emails}

                        if graph_read_map:
                            # Get locally unread emails that might have been read
                            local_unread = await db.execute(
                                select(Email).where(
                                    Email.mailbox == mailbox,
                                    Email.user_id == user_id,
                                    Email.is_read == False,
                                    Email.received_at >= reconcile_since,
                                )
                            )
                            for local_email in local_unread.scalars().all():
                                if local_email.id in graph_read_map and graph_read_map[local_email.id]:
                                    local_email.is_read = True
                                    read_status_updated += 1
                    except Exception as e:
                        logger.warning(f"Read-status reconciliation failed for {mailbox}: {e}")
                        try:
                            await db.rollback()
                        except Exception:
                            pass

                    # Update sync state
                    if sync_state:
                        sync_state.last_sync_at = local_now()
                        sync_state.last_sync_count = synced_count
                        sync_state.last_sync_errors = total_errors
                    else:
                        sync_state = EmailSyncState(
                            user_id=user_id,
                            mailbox=mailbox,
                            last_sync_at=local_now(),
                            last_sync_count=synced_count,
                            last_sync_errors=0
                        )
                        db.add(sync_state)

                    await db.commit()
                    total_synced += synced_count
                    total_read_updated += read_status_updated
                    if read_status_updated > 0:
                        logger.info(f"Synced {synced_count} emails from {mailbox}, updated read status for {read_status_updated} existing emails")
                    else:
                        logger.info(f"Synced {synced_count} emails from {mailbox}")

                    if synced_count > 0:
                        # Only analyze when there are actually new emails
                        analyze_recent_emails.apply_async(
                            args=[mailbox, user_id],
                            queue="low_priority",
                            expires=300,
                        )

                    if synced_count > 0:
                        # Track in unified context changes
                        try:
                            from app.services.context_writer import append_change
                            await append_change(user_id, f"{synced_count} new email(s) in {mailbox}")
                        except Exception:
                            pass

                except Exception as e:
                    logger.error(f"Failed to sync mailbox {mailbox}: {e}")
                    total_errors += 1
                    continue

        return {
            "timestamp": local_now().isoformat(),
            "emails_synced": total_synced,
            "read_status_updated": total_read_updated,
            "errors": total_errors,
            "mailboxes": len(settings.msgraph_mailboxes)
        }

    finally:
        await engine.dispose()


@celery_app.task(
    name="app.tasks.email_sync.analyze_recent_emails",
    bind=True,
    queue="cognitive"
)
def analyze_recent_emails(self, mailbox: str, user_id: str):
    """
    Analyze recently synced emails for a mailbox.
    Categorizes, summarizes, and scores importance.
    """
    logger.info(f"Analyzing emails for {mailbox}")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _analyze_emails_async(mailbox, user_id)
        )
        logger.info(f"Email analysis complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_analyze_emails_async(mailbox, user_id))
        logger.info(f"Email analysis complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Email analysis failed: {e}")
        raise


async def _analyze_emails_async(mailbox: str, user_id: str):
    """Async implementation of email analysis."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select

    from app.models.email import Email, EmailAttachment
    from app.services.notification_service import get_notification_service
    from app.core.config import settings

    database_url = os.getenv("DATABASE_URL", "")

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    analyzed_count = 0
    notifications_sent = 0

    try:
        async with async_session() as db:
            # Get unanalyzed emails from this mailbox
            result = await db.execute(
                select(Email).where(
                    Email.mailbox == mailbox,
                    Email.user_id == user_id,
                    Email.analyzed_at.is_(None)
                ).order_by(Email.received_at.desc()).limit(50)
            )
            emails = list(result.scalars().all())

            # Also retry emails that were analyzed but may have missed meetings:
            # analyzed, no calendar event, received in the last 7 days, not already
            # flagged as has_meeting=True (those succeeded but event creation failed)
            from sqlalchemy import and_, or_
            retry_result = await db.execute(
                select(Email).where(
                    Email.mailbox == mailbox,
                    Email.user_id == user_id,
                    Email.analyzed_at.isnot(None),
                    Email.calendar_event_id.is_(None),
                    or_(Email.has_meeting.is_(None), Email.has_meeting == False),
                    Email.received_at >= local_now() - timedelta(days=7),
                ).order_by(Email.received_at.desc()).limit(20)
            )
            retry_emails = retry_result.scalars().all()
            # Retry emails are for MEETING DETECTION ONLY — they've already
            # been triaged once and should never fire a push notification.
            # Previously the loop re-ran the full notification gate on them
            # every 3-min sync, spamming the user about old emails.
            retry_ids = {e.id for e in retry_emails}
            if retry_emails:
                logger.info(f"Retrying meeting detection for {len(retry_emails)} previously-analyzed emails")
                emails.extend(retry_emails)

            notification_service = get_notification_service()

            for email in emails:
                try:
                    # First, check for ICS calendar invite attachments
                    ics_meeting_info = None
                    if not email.calendar_event_id:
                        ics_meeting_info = await _check_for_ics_attachment(
                            db, email, settings.msgraph_mailboxes[0] if settings.msgraph_mailboxes else email.mailbox
                        )

                    # Analyze the email with LLM
                    analysis = await _analyze_single_email(email)

                    # If we found an ICS attachment, use that meeting info (more accurate)
                    if ics_meeting_info:
                        analysis["has_meeting"] = True
                        analysis["meeting_info"] = ics_meeting_info
                        analysis["category"] = "meeting"
                        if analysis["importance_score"] < 0.7:
                            analysis["importance_score"] = 0.7

                    # Update email with analysis results
                    email.category = analysis["category"]
                    email.importance_score = analysis["importance_score"]
                    email.summary = analysis["summary"]
                    email.action_required = analysis["action_required"]
                    email.analyzed_at = local_now()
                    email.has_meeting = analysis.get("has_meeting", False)

                    # Create calendar event if this is a meeting email
                    if analysis.get("has_meeting") and analysis.get("meeting_info") and not email.calendar_event_id:
                        try:
                            event_id = await _create_calendar_event_from_email(
                                db, user_id, email, analysis["meeting_info"]
                            )
                            if event_id:
                                email.calendar_event_id = event_id
                                email.calendar_event_created_at = local_now()
                                source_type = "ICS attachment" if ics_meeting_info else "email content"
                                logger.info(f"Created calendar event {event_id} from {source_type}: {email.subject}")
                        except Exception as e:
                            logger.error(f"Failed to create calendar event from email: {e}")
                            try:
                                await db.rollback()
                            except Exception:
                                pass

                    # Check if we should send a notification
                    should_notify = False
                    notify_reason = None

                    if analysis["importance_score"] >= 0.8:
                        should_notify = True
                        notify_reason = "high_importance"
                    elif analysis["category"] == "support":
                        should_notify = True
                        notify_reason = "support_request"
                    elif analysis["category"] == "urgent":
                        should_notify = True
                        notify_reason = "urgent_email"

                    # Check for RiskNinja-relevant attachments
                    att_result = await db.execute(
                        select(EmailAttachment).where(
                            EmailAttachment.email_id == email.id,
                            EmailAttachment.is_riskninja_relevant == True
                        )
                    )
                    rn_attachments = att_result.scalars().all()
                    if rn_attachments:
                        should_notify = True
                        notify_reason = "riskninja_attachment"

                    # Send notification if needed. Skip entirely for retry
                    # emails — they were already triaged on their first pass,
                    # and this loop is only re-visiting them for meeting
                    # detection. Re-notifying would spam the user about every
                    # old email every 3 minutes.
                    is_retry = email.id in retry_ids
                    if should_notify and not email.notification_sent and not is_retry:
                        await notification_service.notify_david(
                            title=f"New {analysis['category'].title()} Email",
                            body=f"From: {email.sender_name or email.sender_email}\n{email.subject}\n\n{analysis['summary'][:200]}",
                            priority="high" if analysis["importance_score"] >= 0.8 else "normal",
                            category="email",
                            topic=f"email:{email.id}",
                            url=f"https://sara.avery.cloud/email/{email.id}"
                        )
                        email.notification_sent = True
                        email.notification_sent_at = local_now()
                        notifications_sent += 1

                    analyzed_count += 1

                except Exception as e:
                    logger.error(f"Failed to analyze email {email.id}: {e}")
                    continue

            await db.commit()

            # Trigger RiskNinja attachment processing after analysis
            # The task will check if there are any pending attachments to process
            if analyzed_count > 0:
                process_riskninja_attachments.delay()

        return {
            "mailbox": mailbox,
            "analyzed": analyzed_count,
            "notifications_sent": notifications_sent
        }

    finally:
        await engine.dispose()


async def _check_for_ics_attachment(db, email, mailbox: str) -> Optional[Dict[str, Any]]:
    """
    Check if an email has an ICS calendar attachment and parse it.

    Args:
        db: Database session
        email: Email object
        mailbox: Mailbox address for API calls

    Returns:
        Meeting info dict if ICS found and parsed, None otherwise
    """
    from sqlalchemy import select
    from app.models.email import EmailAttachment
    from app.services.msgraph_service import get_msgraph_service

    try:
        # Check for ICS attachments
        result = await db.execute(
            select(EmailAttachment).where(
                EmailAttachment.email_id == email.id
            )
        )
        attachments = result.scalars().all()

        for attachment in attachments:
            filename_lower = attachment.filename.lower()

            # Check for ICS file extension or content type
            is_ics = (
                filename_lower.endswith('.ics') or
                filename_lower.endswith('.ical') or
                attachment.content_type in (
                    'text/calendar',
                    'application/ics',
                    'application/icalendar'
                )
            )

            if is_ics:
                logger.info(f"Found ICS attachment: {attachment.filename} in email: {email.subject}")

                # Parse the ICS attachment
                msgraph = get_msgraph_service()
                meeting_info = await _parse_ics_from_attachment(
                    msgraph, mailbox, email.id, attachment.id, attachment.filename
                )

                if meeting_info:
                    logger.info(f"Parsed ICS: {meeting_info.get('title')} at {meeting_info.get('start_time')}")
                    return meeting_info

        return None

    except Exception as e:
        logger.error(f"Error checking for ICS attachment: {e}")
        return None


async def _parse_ics_from_attachment(
    msgraph,
    mailbox: str,
    email_id: str,
    attachment_id: str,
    attachment_name: str
) -> Optional[Dict[str, Any]]:
    """
    Download and parse an ICS calendar attachment.

    Returns:
        Dict with meeting_info if successful, None otherwise
    """
    try:
        # Download the ICS file content
        content = await msgraph.download_attachment(mailbox, email_id, attachment_id)
        if not content:
            logger.warning(f"Empty ICS attachment: {attachment_name}")
            return None

        # Decode the content
        ics_text = content.decode('utf-8', errors='replace')

        return _parse_ics_content(ics_text)

    except Exception as e:
        logger.error(f"Failed to parse ICS attachment {attachment_name}: {e}")
        return None


def _parse_ics_content(ics_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse ICS/iCalendar content and extract meeting details.

    Args:
        ics_text: Raw ICS file content as string

    Returns:
        Dict with title, start_time, end_time, location, description, organizer
    """
    try:
        # Try using icalendar library if available
        try:
            from icalendar import Calendar
            cal = Calendar.from_ical(ics_text)

            for component in cal.walk():
                if component.name == "VEVENT":
                    # Extract event details
                    summary = str(component.get('summary', '')) or 'Meeting'
                    location = str(component.get('location', '')) or ''
                    description = str(component.get('description', '')) or ''

                    # Parse start time
                    dtstart = component.get('dtstart')
                    if dtstart:
                        start_dt = dtstart.dt
                        # Handle date vs datetime
                        if hasattr(start_dt, 'hour'):
                            # It's a datetime - ensure timezone aware
                            if start_dt.tzinfo is None:
                                start_dt = start_dt.replace(tzinfo=USER_TIMEZONE)
                            start_time = start_dt.astimezone(ZoneInfo("UTC"))
                        else:
                            # It's a date (all-day event)
                            start_time = datetime.combine(start_dt, datetime.min.time(), tzinfo=USER_TIMEZONE)
                            start_time = start_time.astimezone(ZoneInfo("UTC"))
                    else:
                        logger.warning("No DTSTART in ICS event")
                        return None

                    # Parse end time
                    dtend = component.get('dtend')
                    if dtend:
                        end_dt = dtend.dt
                        if hasattr(end_dt, 'hour'):
                            if end_dt.tzinfo is None:
                                end_dt = end_dt.replace(tzinfo=USER_TIMEZONE)
                            end_time = end_dt.astimezone(ZoneInfo("UTC"))
                        else:
                            end_time = datetime.combine(end_dt, datetime.max.time(), tzinfo=USER_TIMEZONE)
                            end_time = end_time.astimezone(ZoneInfo("UTC"))
                    else:
                        # Default to 1 hour duration
                        end_time = start_time + timedelta(hours=1)

                    # Get organizer
                    organizer = component.get('organizer')
                    organizer_email = ''
                    if organizer:
                        organizer_str = str(organizer)
                        if organizer_str.lower().startswith('mailto:'):
                            organizer_email = organizer_str[7:]
                        else:
                            organizer_email = organizer_str

                    return {
                        "title": summary,
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "location": location,
                        "description": description,
                        "organizer": organizer_email,
                        "source": "ics_attachment"
                    }

            logger.warning("No VEVENT found in ICS content")
            return None

        except ImportError:
            # Fallback to regex parsing if icalendar not available
            logger.info("icalendar library not available, using regex parsing")
            return _parse_ics_with_regex(ics_text)

    except Exception as e:
        logger.error(f"Error parsing ICS content: {e}")
        return None


def _parse_ics_with_regex(ics_text: str) -> Optional[Dict[str, Any]]:
    """
    Fallback regex-based ICS parser when icalendar library is not available.
    """
    from dateutil import parser as dateutil_parser

    try:
        # Extract SUMMARY (title)
        summary_match = re.search(r'SUMMARY[^:]*:(.+?)(?:\r?\n(?!\s)|$)', ics_text, re.DOTALL)
        title = summary_match.group(1).strip() if summary_match else 'Meeting'
        # Handle line folding (lines starting with space are continuations)
        title = re.sub(r'\r?\n\s', '', title)

        # Extract DTSTART
        dtstart_match = re.search(r'DTSTART[^:]*:(\d{8}T?\d{0,6}Z?)', ics_text)
        if not dtstart_match:
            logger.warning("No DTSTART found in ICS")
            return None

        dtstart_str = dtstart_match.group(1)
        start_time = _parse_ics_datetime(dtstart_str)
        if not start_time:
            return None

        # Extract DTEND
        dtend_match = re.search(r'DTEND[^:]*:(\d{8}T?\d{0,6}Z?)', ics_text)
        if dtend_match:
            end_time = _parse_ics_datetime(dtend_match.group(1))
        else:
            end_time = start_time + timedelta(hours=1)

        # Extract LOCATION
        location_match = re.search(r'LOCATION[^:]*:(.+?)(?:\r?\n(?!\s)|$)', ics_text, re.DOTALL)
        location = location_match.group(1).strip() if location_match else ''
        location = re.sub(r'\r?\n\s', '', location)

        # Extract DESCRIPTION
        desc_match = re.search(r'DESCRIPTION[^:]*:(.+?)(?:\r?\n(?!\s)|$)', ics_text, re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else ''
        description = re.sub(r'\r?\n\s', '', description)

        # Extract ORGANIZER
        org_match = re.search(r'ORGANIZER[^:]*:(?:mailto:)?(.+?)(?:\r?\n|$)', ics_text, re.IGNORECASE)
        organizer = org_match.group(1).strip() if org_match else ''

        return {
            "title": title,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat() if end_time else None,
            "location": location,
            "description": description,
            "organizer": organizer,
            "source": "ics_attachment"
        }

    except Exception as e:
        logger.error(f"Regex ICS parsing failed: {e}")
        return None


def _parse_ics_datetime(dt_str: str) -> Optional[datetime]:
    """
    Parse an ICS datetime string (e.g., 20240115T143000Z or 20240115).
    """
    try:
        dt_str = dt_str.strip()

        if 'T' in dt_str:
            # DateTime format: YYYYMMDDTHHMMSS or YYYYMMDDTHHMMSSZ
            if dt_str.endswith('Z'):
                dt = datetime.strptime(dt_str, '%Y%m%dT%H%M%SZ')
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            else:
                dt = datetime.strptime(dt_str, '%Y%m%dT%H%M%S')
                # Assume user's timezone if no Z suffix
                dt = dt.replace(tzinfo=USER_TIMEZONE)
                dt = dt.astimezone(ZoneInfo("UTC"))
        else:
            # Date-only format: YYYYMMDD (all-day event)
            d = datetime.strptime(dt_str, '%Y%m%d').date()
            dt = datetime.combine(d, datetime.min.time(), tzinfo=USER_TIMEZONE)
            dt = dt.astimezone(ZoneInfo("UTC"))

        return dt

    except Exception as e:
        logger.error(f"Failed to parse ICS datetime '{dt_str}': {e}")
        return None


def _normalize_meeting_title(title: str) -> str:
    """Normalize a meeting title for dedup comparison.

    Strips common prefixes like 'Updated invitation:', 'Re:', 'Fwd:' and
    trailing participants/dates so the core meeting name is compared.
    """
    t = title.lower().strip()
    for prefix in ["updated invitation:", "invitation:", "accepted:", "declined:",
                    "tentative:", "canceled:", "cancelled:", "re:", "fwd:", "fw:"]:
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
    # Strip trailing email-style annotations like "@ Mon Mar 2..."
    at_idx = t.find(" @ ")
    if at_idx > 0:
        t = t[:at_idx].strip()
    # Strip trailing parenthesized emails like "(devadmin@riskninja.ai)"
    paren_idx = t.rfind(" (")
    if paren_idx > 0 and t.endswith(")"):
        t = t[:paren_idx].strip()
    return t


async def _create_calendar_event_from_email(
    db,
    user_id: str,
    email,
    meeting_info: Dict[str, Any]
) -> Optional[str]:
    """
    Create a calendar event from email meeting info.

    Args:
        db: Database session
        user_id: User ID to create event for
        email: Email object with meeting details
        meeting_info: Dict with title, start_time, end_time, location, description

    Returns:
        Event ID if created, None otherwise
    """
    from app.tools.calendar import CalendarEvent
    import uuid as uuid_module
    from dateutil import parser as dateutil_parser

    try:
        # Parse meeting times
        start_time_str = meeting_info.get("start_time")
        end_time_str = meeting_info.get("end_time")

        if not start_time_str:
            logger.warning(f"No start_time in meeting_info for email: {email.subject}")
            return None

        # Parse datetime strings.
        #
        # NOTE: The LLM is instructed to emit naive local (Eastern) times. ICS
        # attachments DO carry real timezone info and go through a separate
        # path (_parse_ics_content) that already converts properly, so by the
        # time meeting_info gets here from the LLM path, any offset present is
        # almost certainly the LLM hallucinating "-05:00" from a stale prompt
        # example — which silently shifts the wall-clock time by an hour
        # whenever DST is in effect. To avoid that class of bug, we treat the
        # LLM's datetime as a wall-clock string: strip any tzinfo and re-stamp
        # with the user's current Eastern timezone (DST-aware via ZoneInfo).
        is_from_ics = (meeting_info.get("source") == "ics_attachment")

        def _parse_meeting_dt(value: str) -> Optional[datetime]:
            try:
                dt = dateutil_parser.parse(value)
            except Exception as exc:
                logger.warning(f"Failed to parse meeting datetime '{value}': {exc}")
                return None
            if is_from_ics:
                # ICS path is trusted — keep its tz, normalize to ET, drop tz.
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=USER_TIMEZONE)
                return dt.astimezone(USER_TIMEZONE).replace(tzinfo=None)
            # LLM path — discard any offset and treat as local Eastern wall time.
            if dt.tzinfo is not None:
                logger.info(
                    f"Stripping LLM-supplied offset {dt.tzinfo} from '{value}' "
                    f"and treating as local Eastern (DST-aware)"
                )
                dt = dt.replace(tzinfo=None)
            return dt

        start_time = _parse_meeting_dt(start_time_str)
        if start_time is None:
            return None

        # End time - default to 1 hour after start if not provided
        if end_time_str:
            end_time = _parse_meeting_dt(end_time_str) or (start_time + timedelta(hours=1))
        else:
            end_time = start_time + timedelta(hours=1)

        # Build event title - use meeting_info title or email subject
        title = meeting_info.get("title") or email.subject or "Meeting"

        # Build description
        description_parts = []
        if meeting_info.get("description"):
            description_parts.append(meeting_info["description"])

        # Add source info
        source_info = meeting_info.get("source", "email")
        if source_info == "ics_attachment":
            description_parts.append(f"\n\n---\nAuto-created by Sara from calendar invite in email:\nFrom: {email.sender_name} <{email.sender_email}>\nSubject: {email.subject}")
        else:
            description_parts.append(f"\n\n---\nAuto-created by Sara from email:\nFrom: {email.sender_name} <{email.sender_email}>\nSubject: {email.subject}")

        description = "\n".join(description_parts)

        # --- Dedup Strategy ---
        # 1. Check if another email in the same conversation already created an event
        # 2. Check for existing events with similar title on the same day
        from sqlalchemy import select, and_, func
        from app.models.email import Email as EmailModel

        # Strategy 1: conversation-based dedup (updated invites share conversation_id)
        if email.conversation_id:
            thread_emails = (await db.execute(
                select(EmailModel).where(
                    EmailModel.conversation_id == email.conversation_id,
                    EmailModel.calendar_event_id.isnot(None),
                    EmailModel.id != email.id,
                )
            )).scalars().all()

            for thread_email in thread_emails:
                # Found a sibling email that already created an event — update it
                existing_event = (await db.execute(
                    select(CalendarEvent).where(
                        CalendarEvent.id == thread_email.calendar_event_id,
                    )
                )).scalar_one_or_none()
                if existing_event:
                    existing_event.start_time = start_time
                    existing_event.end_time = end_time
                    existing_event.title = title
                    existing_event.location = meeting_info.get("location") or existing_event.location
                    existing_event.description = description[:2000]
                    existing_event.updated_at = local_now()
                    await db.flush()
                    logger.info(f"Updated calendar event {existing_event.id} from conversation thread: {title}")
                    return existing_event.id

        # Strategy 2: title+date dedup (same day, similar title)
        day_start = start_time.replace(hour=0, minute=0, second=0)
        day_end = day_start + timedelta(days=1)
        existing = (await db.execute(
            select(CalendarEvent).where(and_(
                CalendarEvent.user_id == user_id,
                CalendarEvent.start_time >= day_start,
                CalendarEvent.start_time < day_end,
                CalendarEvent.source == "email_sync",
            ))
        )).scalars().all()

        new_title_norm = _normalize_meeting_title(title)
        for ex in existing:
            ex_title_norm = _normalize_meeting_title(ex.title)
            if ex_title_norm == new_title_norm or ex_title_norm in new_title_norm or new_title_norm in ex_title_norm:
                # Update existing event (time may have changed)
                ex.start_time = start_time
                ex.end_time = end_time
                ex.location = meeting_info.get("location") or ex.location
                ex.description = description[:2000]
                ex.updated_at = local_now()
                await db.flush()
                logger.info(f"Updated existing calendar event {ex.id} (title match): {title}")
                return ex.id

        # Create the calendar event
        event = CalendarEvent(
            id=str(uuid_module.uuid4()),
            user_id=user_id,
            title=title,
            description=description[:2000],  # Limit description length
            start_time=start_time,
            end_time=end_time,
            location=meeting_info.get("location") or "",
            all_day=False,
            source="email_sync",
            is_completed=False
        )

        db.add(event)
        await db.flush()

        return event.id

    except Exception as e:
        logger.error(f"Error creating calendar event: {e}")
        return None


async def _analyze_single_email(email) -> Dict[str, Any]:
    """
    Analyze a single email using LLM.
    Returns category, importance score, summary, action_required flag, and meeting info.
    """
    import httpx
    from app.core.config import settings

    # Prepare email content for analysis
    email_content = f"""
Subject: {email.subject}
From: {email.sender_name} <{email.sender_email}>
Received: {email.received_at.isoformat()}

{email.body_text[:3000] if email.body_text else email.body_preview}
"""

    prompt = f"""Analyze this email and provide a JSON response with the following fields:
1. category: One of "support", "urgent", "sales", "internal", "newsletter", "personal", "financial", "notification", "meeting"
2. importance_score: A float from 0.0 to 1.0 indicating importance (1.0 = critical)
3. summary: A 1-2 sentence summary of the email's key points
4. action_required: true if this email requires a response or action, false otherwise
5. has_meeting: true ONLY if this email is a direct meeting invitation or scheduling request where David is a participant. NOT true for: webinars, online events, newsletters mentioning events, marketing emails about conferences, digest emails
6. meeting_info: If has_meeting is true, provide meeting details as an object:
   - title: Meeting title/subject (clean, no "Updated invitation:" prefix)
   - start_time: ISO 8601 LOCAL datetime, NO timezone offset suffix
     (e.g., "2026-04-06T10:00:00"). Use the wall-clock time as stated in
     the email body. Do NOT append "Z", "-05:00", "-04:00", or any other
     offset — the server will apply the user's current Eastern timezone
     and handle DST correctly. Inventing an offset will cause the
     resulting calendar event to be off by one hour.
   - end_time: ISO 8601 LOCAL datetime, NO timezone offset suffix
   - location: Meeting location or video call link (null if not specified)
   - description: Brief description or agenda

Consider these factors for importance:
- Support requests from customers = high importance
- Urgent keywords (urgent, asap, critical, deadline) = high importance
- Newsletters and marketing = low importance
- Internal team updates = medium importance
- Financial/billing matters = medium-high importance
- Automated notifications = low importance
- Direct meeting invitations (1-on-1, team calls) = medium-high importance
- Webinars, online events, mass invitations = low importance (NOT has_meeting)

Email:
{email_content}

Respond ONLY with valid JSON, no markdown or explanation:"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Build headers - only include Authorization if API key is set and not dummy
            headers = {}
            api_key = settings.openai_api_key
            if api_key and api_key not in ("", "dummy", "sk-"):
                headers["Authorization"] = f"Bearer {api_key}"

            response = await client.post(
                f"{settings.bg_llm_primary_url}/chat/completions",
                json={
                    "model": settings.bg_llm_primary_model,
                    "messages": [
                        {"role": "system", "content": "You are an email analysis assistant. Respond only with valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 500,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                headers=headers if headers else None
            )

            if response.status_code != 200:
                raise Exception(f"LLM request failed: {response.status_code}")

            data = response.json()
            content = data["choices"][0]["message"]["content"] or ""
            finish_reason = data["choices"][0].get("finish_reason", "unknown")

            # Guard against empty content (thinking mode may consume all tokens)
            if not content.strip():
                logger.warning(f"Email analysis LLM returned empty content (finish_reason={finish_reason}), using fallback")
                return _fallback_analysis(email)

            # Parse JSON response
            import json
            # Clean up potential markdown formatting
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]

            analysis = json.loads(content)

            # Validate and normalize response
            return {
                "category": analysis.get("category", "notification").lower(),
                "importance_score": min(1.0, max(0.0, float(analysis.get("importance_score", 0.5)))),
                "summary": analysis.get("summary", email.body_preview[:200]),
                "action_required": bool(analysis.get("action_required", False)),
                "has_meeting": bool(analysis.get("has_meeting", False)),
                "meeting_info": analysis.get("meeting_info", None)
            }

    except Exception as e:
        logger.error(f"Email analysis LLM error: {e}")
        # Return fallback analysis
        return _fallback_analysis(email)


def _fallback_analysis(email) -> Dict[str, Any]:
    """
    Simple rule-based fallback analysis when LLM is unavailable.
    """
    subject_lower = email.subject.lower() if email.subject else ""
    sender_lower = email.sender_email.lower() if email.sender_email else ""
    body_lower = (email.body_text or email.body_preview or "").lower()

    # Determine category
    category = "notification"
    importance = 0.3
    has_meeting = False
    meeting_info = None

    # Check for meeting indicators
    meeting_keywords = ["meeting", "invite", "calendar", "schedule", "call", "zoom", "teams", "webex", "appointment"]
    if any(kw in subject_lower or kw in body_lower for kw in meeting_keywords):
        # Check for more specific meeting patterns
        if any(pattern in subject_lower for pattern in ["invited you to", "meeting invite", "calendar event", "join us"]):
            has_meeting = True
            category = "meeting"
            importance = 0.7
        elif "when:" in body_lower or "date:" in body_lower or "time:" in body_lower:
            has_meeting = True
            category = "meeting"
            importance = 0.7

    # If meeting detected, try to extract datetime from body
    if has_meeting:
        meeting_info = _extract_meeting_info_fallback(email)

    # Check for urgent indicators
    urgent_keywords = ["urgent", "asap", "critical", "deadline", "immediately", "time-sensitive"]
    if any(kw in subject_lower or kw in body_lower for kw in urgent_keywords):
        category = "urgent"
        importance = 0.9

    # Check for support indicators
    support_keywords = ["support", "help", "issue", "problem", "bug", "error", "not working"]
    if any(kw in subject_lower or kw in body_lower for kw in support_keywords):
        category = "support"
        importance = 0.7

    # Check for newsletter/marketing
    newsletter_keywords = ["unsubscribe", "newsletter", "marketing", "promotional", "noreply"]
    if any(kw in subject_lower or kw in sender_lower or kw in body_lower for kw in newsletter_keywords):
        category = "newsletter"
        importance = 0.1

    # Check for financial
    financial_keywords = ["invoice", "payment", "billing", "subscription", "receipt"]
    if any(kw in subject_lower or kw in body_lower for kw in financial_keywords):
        category = "financial"
        importance = 0.6

    # Check for internal
    if "riskninja" in sender_lower:
        category = "internal"
        importance = 0.5

    return {
        "category": category,
        "importance_score": importance,
        "summary": email.body_preview[:200] if email.body_preview else "No preview available",
        "action_required": category in ["urgent", "support"],
        "has_meeting": has_meeting,
        "meeting_info": meeting_info,
    }


def _extract_meeting_info_fallback(email) -> Optional[Dict[str, Any]]:
    """Try to extract meeting time from email body using regex patterns."""
    from dateutil import parser as dateutil_parser

    body = email.body_text or email.body_preview or ""
    subject = email.subject or ""

    # Common patterns: "January 15, 2026 at 2:00 PM", "2026-01-15T14:00:00",
    # "When: Monday, March 2, 2026 10:00 AM", "Date: 3/2/2026 Time: 10:00 AM"
    datetime_patterns = [
        # "When: <datetime>"
        r'when:\s*(.+?)(?:\n|$)',
        # "Date: <date>" followed by optional "Time: <time>"
        r'date:\s*(.+?)(?:\n|$)',
        # ISO format
        r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})',
        # "Month Day, Year at Time"
        r'(\w+\s+\d{1,2},?\s+\d{4}\s+(?:at\s+)?\d{1,2}:\d{2}\s*(?:AM|PM)?)',
    ]

    for pattern in datetime_patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            try:
                dt = dateutil_parser.parse(match.group(1).strip(), fuzzy=True)
                # Assume Eastern timezone if naive
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=USER_TIMEZONE)
                return {
                    "title": subject,
                    "start_time": dt.isoformat(),
                    "end_time": (dt + timedelta(hours=1)).isoformat(),
                    "location": None,
                    "description": f"Auto-detected from email: {subject}",
                }
            except (ValueError, OverflowError):
                continue

    return None


@celery_app.task(
    name="app.tasks.email_sync.download_attachments",
    bind=True,
    queue="cognitive"
)
def download_attachments(self, email_id: str, mailbox: str):
    """
    Download and store attachments for an email in MinIO.
    """
    logger.info(f"Downloading attachments for email {email_id}")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _download_attachments_async(email_id, mailbox)
        )
        logger.info(f"Attachment download complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_download_attachments_async(email_id, mailbox))
        logger.info(f"Attachment download complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Attachment download failed: {e}")
        raise


async def _download_attachments_async(email_id: str, mailbox: str):
    """Async implementation of attachment download."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from minio import Minio
    from io import BytesIO

    from app.models.email import EmailAttachment
    from app.services.msgraph_service import get_msgraph_service
    from app.core.config import settings

    database_url = os.getenv("DATABASE_URL", "")

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    downloaded_count = 0

    try:
        msgraph = get_msgraph_service()

        # Initialize MinIO client
        minio_url = settings.minio_url.replace("http://", "").replace("https://", "")
        minio_client = Minio(
            minio_url,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False
        )

        async with async_session() as db:
            # Get attachments that haven't been downloaded
            result = await db.execute(
                select(EmailAttachment).where(
                    EmailAttachment.email_id == email_id,
                    EmailAttachment.minio_key.is_(None)
                )
            )
            attachments = result.scalars().all()

            for attachment in attachments:
                try:
                    # Download from Graph API
                    content = await msgraph.download_attachment(
                        mailbox, email_id, attachment.id
                    )

                    if not content:
                        logger.warning(f"Empty attachment content for {attachment.id}")
                        continue

                    # Determine bucket
                    if attachment.is_riskninja_relevant:
                        bucket = "riskninja-docs"
                    else:
                        bucket = settings.minio_bucket

                    # Ensure bucket exists
                    if not minio_client.bucket_exists(bucket):
                        minio_client.make_bucket(bucket)

                    # Generate storage key
                    date_prefix = local_now().strftime("%Y/%m/%d")
                    key = f"email-attachments/{date_prefix}/{email_id}/{attachment.filename}"

                    # Upload to MinIO
                    minio_client.put_object(
                        bucket,
                        key,
                        BytesIO(content),
                        length=len(content),
                        content_type=attachment.content_type or "application/octet-stream"
                    )

                    # Update attachment record
                    attachment.minio_bucket = bucket
                    attachment.minio_key = key
                    attachment.downloaded_at = local_now()

                    downloaded_count += 1
                    logger.info(f"Downloaded attachment: {attachment.filename} -> {bucket}/{key}")

                except Exception as e:
                    logger.error(f"Failed to download attachment {attachment.id}: {e}")
                    continue

            await db.commit()

        return {
            "email_id": email_id,
            "downloaded": downloaded_count
        }

    finally:
        await engine.dispose()


# ============================================================================
# RISKNINJA ATTACHMENT FILING AUTOMATION
# ============================================================================

# Configure RiskNinja project ID - this should be set in environment or discovered
RISKNINJA_PROJECT_ID = os.getenv("RISKNINJA_PROJECT_ID", None)
SARAS_FINDINGS_FOLDER = "Sara's Findings"


@celery_app.task(
    name="app.tasks.email_sync.process_riskninja_attachments",
    bind=True,
    queue="low_priority",
    soft_time_limit=120,
    time_limit=150,
)
def process_riskninja_attachments(self):
    """
    Process RiskNinja-relevant attachments and file important ones to Projects.

    This task:
    1. Finds RiskNinja-relevant attachments that haven't been filed
    2. Uses LLM to analyze if the attachment is important (COIs, contracts, etc.)
    3. If important, files to "Sara's Findings" folder in RiskNinja project
    """
    logger.info("Processing RiskNinja attachments for filing")

    try:
        result = asyncio.get_event_loop().run_until_complete(
            _process_riskninja_attachments_async()
        )
        logger.info(f"RiskNinja attachment processing complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_process_riskninja_attachments_async())
        logger.info(f"RiskNinja attachment processing complete: {result}")
        return result
    except Exception as e:
        logger.error(f"RiskNinja attachment processing failed: {e}")
        raise


async def _process_riskninja_attachments_async():
    """Async implementation of RiskNinja attachment processing."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    from minio import Minio
    from io import BytesIO
    import uuid as uuid_module

    from app.models.email import Email, EmailAttachment
    from app.models.project_tracker import DevProject, ProjectFolder, ProjectFile
    from app.core.config import settings

    database_url = os.getenv("DATABASE_URL", "")

    if database_url.startswith("postgresql://"):
        async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    elif database_url.startswith("postgresql+psycopg://"):
        async_url = database_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    else:
        async_url = database_url

    engine = create_async_engine(async_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    processed_count = 0
    filed_count = 0
    skipped_count = 0

    try:
        # Initialize MinIO client
        minio_url = settings.minio_url.replace("http://", "").replace("https://", "")
        minio_client = Minio(
            minio_url,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False
        )

        user_id = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")

        async with async_session() as db:
            # Find RiskNinja project
            project_id = RISKNINJA_PROJECT_ID
            if not project_id:
                # Try to find it by name or prefix
                from sqlalchemy import or_
                result = await db.execute(
                    select(DevProject).where(
                        or_(
                            DevProject.name.ilike("%riskninja%"),
                            DevProject.name.ilike("%risk ninja%"),
                            DevProject.prefix == "RN"
                        )
                    ).limit(1)
                )
                project = result.scalar_one_or_none()
                if project:
                    project_id = project.id
                    logger.info(f"Found RiskNinja project: {project.name} ({project_id})")

            if not project_id:
                logger.warning("No RiskNinja project found - creating one")
                # Create RiskNinja project
                project = DevProject(
                    id=str(uuid_module.uuid4()),
                    user_id=user_id,
                    name="RiskNinja",
                    prefix="RN",
                    description="RiskNinja insurance platform",
                    is_active=True
                )
                db.add(project)
                await db.flush()
                project_id = project.id
                logger.info(f"Created RiskNinja project: {project_id}")

            # Find or create "Sara's Findings" folder
            result = await db.execute(
                select(ProjectFolder).where(
                    ProjectFolder.project_id == project_id,
                    ProjectFolder.name == SARAS_FINDINGS_FOLDER,
                    ProjectFolder.parent_id.is_(None)  # Root level
                )
            )
            findings_folder = result.scalar_one_or_none()

            if not findings_folder:
                findings_folder = ProjectFolder(
                    id=str(uuid_module.uuid4()),
                    project_id=project_id,
                    user_id=user_id,
                    name=SARAS_FINDINGS_FOLDER,
                    parent_id=None
                )
                db.add(findings_folder)
                await db.flush()
                logger.info(f"Created 'Sara's Findings' folder: {findings_folder.id}")

            # Get RiskNinja-relevant attachments that haven't been filed
            result = await db.execute(
                select(EmailAttachment).join(Email).where(
                    EmailAttachment.is_riskninja_relevant == True,
                    EmailAttachment.filed_at.is_(None),
                    EmailAttachment.minio_key.isnot(None)  # Must be downloaded
                ).order_by(Email.received_at.desc()).limit(20)
            )
            attachments = result.scalars().all()

            for attachment in attachments:
                try:
                    processed_count += 1

                    # Get email context for analysis
                    email_result = await db.execute(
                        select(Email).where(Email.id == attachment.email_id)
                    )
                    email = email_result.scalar_one_or_none()

                    if not email:
                        logger.warning(f"Email not found for attachment {attachment.id}")
                        continue

                    # Analyze if the attachment is important
                    analysis = await _analyze_attachment_importance(
                        attachment.filename,
                        attachment.content_type,
                        email.subject,
                        email.sender_email,
                        email.body_text[:500] if email.body_text else ""
                    )

                    if not analysis["is_important"]:
                        # Update to mark as analyzed but not filed
                        attachment.filing_analysis = f"Not filed: {analysis['reason']}"
                        skipped_count += 1
                        logger.info(f"Skipping attachment {attachment.filename}: {analysis['reason']}")
                        continue

                    logger.info(f"Filing important attachment: {attachment.filename}")

                    # Download the file from the email attachment bucket
                    try:
                        response = minio_client.get_object(
                            attachment.minio_bucket,
                            attachment.minio_key
                        )
                        content = response.read()
                        response.close()
                        response.release_conn()
                    except Exception as e:
                        logger.error(f"Failed to download attachment from MinIO: {e}")
                        continue

                    # Generate new storage key for project file
                    file_uuid = str(uuid_module.uuid4())
                    safe_filename = attachment.filename.replace("/", "_").replace("\\", "_")
                    storage_key = f"projects/{project_id}/{file_uuid}_{safe_filename}"

                    # Upload to project storage
                    minio_client.put_object(
                        settings.minio_bucket,
                        storage_key,
                        BytesIO(content),
                        length=len(content),
                        content_type=attachment.content_type or "application/octet-stream"
                    )

                    # Create ProjectFile record
                    project_file = ProjectFile(
                        id=str(uuid_module.uuid4()),
                        project_id=project_id,
                        user_id=user_id,
                        folder_id=findings_folder.id,
                        filename=attachment.filename,
                        storage_key=storage_key,
                        mime_type=attachment.content_type,
                        file_size=len(content),
                        description=f"Auto-filed by Sara from email: {email.subject[:100]}"
                    )
                    db.add(project_file)
                    await db.flush()

                    # Update attachment with filing info
                    attachment.filed_to_project_id = project_id
                    attachment.filed_to_folder_id = findings_folder.id
                    attachment.filed_to_file_id = project_file.id
                    attachment.filed_at = local_now()
                    attachment.filing_analysis = analysis["reason"]

                    filed_count += 1
                    logger.info(f"Filed attachment {attachment.filename} to Sara's Findings")

                except Exception as e:
                    logger.error(f"Failed to process attachment {attachment.id}: {e}")
                    continue

            await db.commit()

        return {
            "processed": processed_count,
            "filed": filed_count,
            "skipped": skipped_count
        }

    finally:
        await engine.dispose()


async def _analyze_attachment_importance(
    filename: str,
    content_type: str,
    email_subject: str,
    sender_email: str,
    email_body_preview: str
) -> Dict[str, Any]:
    """
    Use LLM to analyze if an attachment is important enough to file.

    Important attachments include:
    - Certificates of Insurance (COIs)
    - Policy documents
    - Contracts and agreements
    - Financial documents
    - Compliance documents
    """
    import httpx
    from app.core.config import settings

    context = f"""
Filename: {filename}
Content Type: {content_type or 'unknown'}
Email Subject: {email_subject}
From: {sender_email}
Email Preview: {email_body_preview}
"""

    prompt = f"""Analyze this email attachment and determine if it's an important business document that should be filed.

{context}

Important documents include:
- Certificates of Insurance (COIs), proof of coverage
- Insurance policies and endorsements
- Contracts, agreements, proposals
- Financial documents (invoices, statements)
- Compliance and regulatory documents
- Legal documents
- Technical specifications or requirements

NOT important:
- Marketing materials, brochures
- Newsletters
- Generic automated reports
- Temporary or draft documents
- Images/logos without business value

Respond with JSON only:
{{
  "is_important": true or false,
  "reason": "Brief explanation (1-2 sentences)",
  "document_type": "COI/policy/contract/financial/compliance/other/not_important"
}}"""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {}
            api_key = settings.openai_api_key
            if api_key and api_key not in ("", "dummy", "sk-"):
                headers["Authorization"] = f"Bearer {api_key}"

            response = await client.post(
                f"{settings.bg_llm_primary_url}/chat/completions",
                json={
                    "model": settings.bg_llm_primary_model,
                    "messages": [
                        {"role": "system", "content": "You are a document classification assistant. Respond only with valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 300,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                headers=headers if headers else None
            )

            if response.status_code != 200:
                raise Exception(f"LLM request failed: {response.status_code}")

            data = response.json()
            content = data["choices"][0]["message"]["content"] or ""

            if not content.strip():
                logger.warning("Attachment analysis LLM returned empty, using fallback")
                return _fallback_attachment_analysis(filename, content_type, email_subject)

            # Parse JSON response
            import json
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]

            analysis = json.loads(content)

            return {
                "is_important": analysis.get("is_important", False),
                "reason": analysis.get("reason", "Unknown"),
                "document_type": analysis.get("document_type", "other")
            }

    except Exception as e:
        logger.error(f"Attachment analysis LLM error: {e}")
        # Fallback to rule-based analysis
        return _fallback_attachment_analysis(filename, content_type, email_subject)


def _fallback_attachment_analysis(
    filename: str,
    content_type: str,
    email_subject: str
) -> Dict[str, Any]:
    """
    Rule-based fallback for attachment importance analysis.
    """
    lower_filename = filename.lower()
    lower_subject = (email_subject or "").lower()

    # Important document indicators
    important_keywords = [
        "certificate", "coi", "insurance", "policy", "coverage",
        "contract", "agreement", "proposal", "quote",
        "invoice", "statement", "billing",
        "compliance", "audit", "regulatory",
        "endorsement", "acord", "binder"
    ]

    # Check filename
    for keyword in important_keywords:
        if keyword in lower_filename:
            return {
                "is_important": True,
                "reason": f"Filename contains '{keyword}' - likely important business document",
                "document_type": "business_document"
            }

    # Check email subject
    for keyword in important_keywords:
        if keyword in lower_subject:
            return {
                "is_important": True,
                "reason": f"Email subject contains '{keyword}' - attachment likely important",
                "document_type": "business_document"
            }

    # Check for common important file types
    important_extensions = ['.pdf', '.docx', '.xlsx']
    for ext in important_extensions:
        if lower_filename.endswith(ext):
            # Default to important for these types from RiskNinja-relevant emails
            return {
                "is_important": True,
                "reason": f"Document type ({ext}) from RiskNinja-related email - filing for review",
                "document_type": "document"
            }

    return {
        "is_important": False,
        "reason": "No important document indicators found",
        "document_type": "not_important"
    }
