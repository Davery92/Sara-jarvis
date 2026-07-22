"""
Email sync Celery tasks for Microsoft Graph integration.

Handles:
- Periodic email sync from configured mailboxes
- Email analysis (categorization, summarization, importance scoring)
- Attachment processing and RiskNinja detection
- Push notification triggers for important emails

Note: automatic calendar-event creation from emails was removed — the real
calendar syncs from David's phone (ios_calendar source). Meeting detection
survives only as the has_meeting classification flag.
"""

import logging
import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from html import unescape

from app.celery_app import celery_app
from app.core.timezone import now as local_now, to_naive_utc

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
    name="app.tasks.email_sync.sync_sent_items",
    bind=True,
    queue="low_priority",
    max_retries=2,
)
def sync_sent_items(self):
    """SARA_UNLEASHED Phase D.2: sync the Sent folder so the person layer
    sees who David wrote to, not just who wrote to him. Unlocks reply-latency
    ("Jim wrote 3 days ago, you haven't answered") — inbound-only analysis
    can never produce that signal. Does not store full sent-item rows in the
    `email` table (that model's shape is inbound-oriented); only upserts
    each recipient as a person with direction='email_out'."""
    try:
        result = asyncio.get_event_loop().run_until_complete(_sync_sent_items_async())
        logger.info(f"Sent-items sync complete: {result}")
        return result
    except RuntimeError:
        result = asyncio.run(_sync_sent_items_async())
        logger.info(f"Sent-items sync complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Sent-items sync failed: {e}")
        raise self.retry(countdown=120, exc=e)


async def _sync_sent_items_async():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select

    from app.services.msgraph_service import get_msgraph_service
    from app.services.person_service import upsert_person_from_email
    from app.models.email import EmailSyncState
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

    user_id = os.getenv("SOLO_USER_ID", "64f37c56-85cb-4590-8de9-adfc17d343ed")
    total_recipients = 0
    total_sent = 0
    total_errors = 0

    try:
        msgraph = get_msgraph_service()
        async with async_session() as db:
            for mailbox in settings.msgraph_mailboxes:
                # Distinct sync-state key ("::sent") so this shares the
                # EmailSyncState table without colliding with the inbound
                # sync's own per-mailbox row.
                state_key = f"{mailbox}::sent"
                try:
                    result = await db.execute(
                        select(EmailSyncState).where(
                            EmailSyncState.user_id == user_id,
                            EmailSyncState.mailbox == state_key,
                        )
                    )
                    sync_state = result.scalar_one_or_none()
                    since = sync_state.last_sync_at if sync_state and sync_state.last_sync_at else (
                        local_now() - timedelta(hours=24)
                    )
                    # B5: the cursor stalled for weeks because `since` comes back
                    # NAIVE from the DB while msgraph's received_at is AWARE — the
                    # `received_at > latest_at` comparison raised TypeError, was
                    # swallowed by the outer except, and the state was never
                    # committed (cursor frozen, same window re-fetched forever).
                    # Normalize everything to naive-UTC so comparisons are valid
                    # and the stored cursor matches the naive DB column.
                    since = to_naive_utc(since)

                    sent_emails = await msgraph.get_emails(mailbox, since=since, top=50, folder="sentitems")
                    total_sent += len(sent_emails)

                    latest_at = since
                    for sent in sent_emails:
                        recv = to_naive_utc(sent.received_at) if sent.received_at else None
                        if recv and recv > latest_at:
                            latest_at = recv
                        for recipient in (sent.to_recipients or []) + (sent.cc_recipients or []):
                            r_email = (recipient.get("email") or "").strip()
                            if not r_email:
                                continue
                            try:
                                person_id = await upsert_person_from_email(
                                    db, user_id, r_email, recipient.get("name"),
                                    direction="email_out",
                                )
                                if person_id:
                                    total_recipients += 1
                            except Exception as e:
                                logger.warning(f"[sent-sync] person upsert failed for {r_email}: {e}")

                    if sync_state:
                        sync_state.last_sync_at = latest_at
                        sync_state.last_sync_count = len(sent_emails)
                    else:
                        sync_state = EmailSyncState(
                            user_id=user_id, mailbox=state_key,
                            last_sync_at=latest_at, last_sync_count=len(sent_emails), last_sync_errors=0,
                        )
                        db.add(sync_state)
                    await db.commit()
                except Exception as e:
                    logger.error(f"Sent-items sync failed for {mailbox}: {e}")
                    total_errors += 1
                    continue

        return {
            "timestamp": local_now().isoformat(),
            "sent_items_seen": total_sent,
            "recipients_upserted": total_recipients,
            "errors": total_errors,
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


# Minimum LLM importance score (0..1) an email must clear to ping David — and
# even then only if it also needs a response (see should_notify below). Raise
# toward 1.0 for fewer pings, lower for more. Kept here as one knob.
EMAIL_NOTIFY_IMPORTANCE_MIN = 0.8


async def _analyze_emails_async(mailbox: str, user_id: str):
    """Async implementation of email analysis."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select

    from app.models.email import Email
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

            notification_service = get_notification_service()

            for email in emails:
                try:
                    # Analyze the email with LLM
                    analysis = await _analyze_single_email(email)

                    # Update email with analysis results. has_meeting stays a
                    # classification flag only — auto-creating calendar events
                    # from emails was removed; the real calendar syncs from
                    # David's phone (ios_calendar source).
                    email.category = analysis["category"]
                    email.importance_score = analysis["importance_score"]
                    email.summary = analysis["summary"]
                    email.action_required = analysis["action_required"]
                    email.analyzed_at = local_now()
                    email.has_meeting = analysis.get("has_meeting", False)

                    # People layer: upsert the sender going forward (Phase 2).
                    try:
                        from app.services.person_service import upsert_person_from_email
                        await upsert_person_from_email(
                            db, user_id, email.sender_email, email.sender_name,
                            category=analysis["category"],
                        )
                    except Exception as e:
                        logger.warning(f"[email_sync] person upsert failed for {email.id}: {e}")

                    # Notify ONLY when the mail genuinely needs David: it must
                    # BOTH be high-importance AND require an action/response from
                    # him. Everything else — FYI mail, newsletters, automated
                    # notifications, support/sales chatter that doesn't need him —
                    # stays silent; he reads the inbox on his own schedule. This
                    # replaces the old "ping on importance>=0.8 OR support OR
                    # urgent OR any RiskNinja attachment" rule that fired on
                    # nearly every new message.
                    should_notify = (
                        analysis["action_required"]
                        and analysis["importance_score"] >= EMAIL_NOTIFY_IMPORTANCE_MIN
                    )
                    notify_reason = "needs_response" if should_notify else None

                    # Send notification if needed. Dedup by conversation thread,
                    # not per-message — an active back-and-forth ("Re: Re: ...")
                    # used to push on every single reply because each message id
                    # was a fresh topic. Thread-keyed topics let the 4h email
                    # cooldown actually apply to follow-ups.
                    if should_notify and not email.notification_sent:
                        await notification_service.notify_david(
                            title=f"New {analysis['category'].title()} Email",
                            body=f"From: {email.sender_name or email.sender_email}\n{email.subject}\n\n{analysis['summary'][:200]}",
                            priority="high" if analysis["importance_score"] >= 0.8 else "normal",
                            category="email",
                            topic=f"email-thread:{email.conversation_id or email.id}",
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
    }


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

            # Get RiskNinja-relevant attachments that haven't been assessed yet.
            # Idempotence: `filing_analysis` is set on BOTH filing and skipping, so
            # it's the per-attachment "assessed" marker. Previously the query only
            # excluded `filed_at IS NOT NULL`, so every skipped attachment (analyzed
            # but not filed) stayed NULL and was re-downloaded + re-evaluated every
            # 15 min forever — the same 20 attachments, blowing SoftTimeLimitExceeded.
            result = await db.execute(
                select(EmailAttachment).join(Email).where(
                    EmailAttachment.is_riskninja_relevant == True,
                    EmailAttachment.filed_at.is_(None),
                    EmailAttachment.filing_analysis.is_(None),  # not yet assessed
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
