"""
Microsoft Graph API Service
OAuth 2.0 Client Credentials flow for email access (Application permissions)
"""
import httpx
import time
import logging
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class MSGraphAttachment:
    """Represents an email attachment from Microsoft Graph"""
    id: str
    name: str
    content_type: str
    size: int
    is_inline: bool = False
    content_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "content_type": self.content_type,
            "size": self.size,
            "is_inline": self.is_inline,
            "content_id": self.content_id
        }


@dataclass
class MSGraphEmail:
    """Represents an email from Microsoft Graph"""
    id: str
    conversation_id: Optional[str]
    subject: str
    sender_email: str
    sender_name: str
    received_at: datetime
    body_preview: str
    body_content: str
    body_content_type: str  # "text" or "html"
    importance: str  # "low", "normal", "high"
    is_read: bool
    has_attachments: bool
    attachments: List[MSGraphAttachment] = field(default_factory=list)
    to_recipients: List[Dict[str, str]] = field(default_factory=list)
    cc_recipients: List[Dict[str, str]] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    internet_message_id: Optional[str] = None
    parent_folder_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "subject": self.subject,
            "sender_email": self.sender_email,
            "sender_name": self.sender_name,
            "received_at": self.received_at.isoformat(),
            "body_preview": self.body_preview,
            "body_content": self.body_content,
            "body_content_type": self.body_content_type,
            "importance": self.importance,
            "is_read": self.is_read,
            "has_attachments": self.has_attachments,
            "attachments": [a.to_dict() for a in self.attachments],
            "to_recipients": self.to_recipients,
            "cc_recipients": self.cc_recipients,
            "categories": self.categories,
            "internet_message_id": self.internet_message_id,
            "parent_folder_id": self.parent_folder_id
        }


class MSGraphService:
    """
    Microsoft Graph API client using OAuth 2.0 Client Credentials flow.
    Handles token management and email API requests.

    Requires Application permission: Mail.Read (with admin consent)
    """

    TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str,
        mailboxes: List[str]
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.mailboxes = mailboxes
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    async def _get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary"""
        # Check if we have a valid token with 5 minute buffer
        if self._access_token and time.time() < (self._token_expires_at - 300):
            return self._access_token

        # Request new token
        token_url = self.TOKEN_URL.format(tenant_id=self.tenant_id)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials"
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                }
            )

            if response.status_code != 200:
                logger.error(f"MS Graph token request failed: {response.status_code} {response.text}")
                raise Exception(f"Failed to get MS Graph access token: {response.status_code}")

            data = response.json()
            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + data.get("expires_in", 3600)

            logger.info("MS Graph access token refreshed")
            return self._access_token

    async def _api_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Make an authenticated API request to MS Graph"""
        token = await self._get_access_token()

        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
            )

            if response.status_code == 204:
                return {}

            if response.status_code not in (200, 201):
                logger.error(f"MS Graph API error: {response.status_code} {response.text}")
                raise Exception(f"MS Graph API error: {response.status_code}")

            return response.json()

    async def _api_request_raw(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> bytes:
        """Make an authenticated API request and return raw bytes (for attachment download)"""
        token = await self._get_access_token()

        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}"
                }
            )

            if response.status_code != 200:
                logger.error(f"MS Graph API error: {response.status_code}")
                raise Exception(f"MS Graph API error: {response.status_code}")

            return response.content

    def _parse_email(self, data: Dict[str, Any]) -> MSGraphEmail:
        """Parse raw Graph API response into MSGraphEmail object"""
        sender = data.get("from", {}).get("emailAddress", {})
        body = data.get("body", {})

        # Parse received datetime
        received_str = data.get("receivedDateTime", "")
        if received_str:
            # Handle ISO format with Z suffix
            if received_str.endswith("Z"):
                received_str = received_str[:-1] + "+00:00"
            received_at = datetime.fromisoformat(received_str)
        else:
            received_at = datetime.now(timezone.utc)

        # Parse recipients
        to_recipients = [
            {"email": r.get("emailAddress", {}).get("address", ""),
             "name": r.get("emailAddress", {}).get("name", "")}
            for r in data.get("toRecipients", [])
        ]
        cc_recipients = [
            {"email": r.get("emailAddress", {}).get("address", ""),
             "name": r.get("emailAddress", {}).get("name", "")}
            for r in data.get("ccRecipients", [])
        ]

        return MSGraphEmail(
            id=data.get("id", ""),
            conversation_id=data.get("conversationId"),
            subject=data.get("subject", "(No Subject)"),
            sender_email=sender.get("address", ""),
            sender_name=sender.get("name", ""),
            received_at=received_at,
            body_preview=data.get("bodyPreview", "")[:255],
            body_content=body.get("content", ""),
            body_content_type=body.get("contentType", "text").lower(),
            importance=data.get("importance", "normal"),
            is_read=data.get("isRead", False),
            has_attachments=data.get("hasAttachments", False),
            attachments=[],
            to_recipients=to_recipients,
            cc_recipients=cc_recipients,
            categories=data.get("categories", []),
            internet_message_id=data.get("internetMessageId"),
            parent_folder_id=data.get("parentFolderId")
        )

    def _parse_attachment(self, data: Dict[str, Any]) -> MSGraphAttachment:
        """Parse raw Graph API attachment response"""
        return MSGraphAttachment(
            id=data.get("id", ""),
            name=data.get("name", ""),
            content_type=data.get("contentType", "application/octet-stream"),
            size=data.get("size", 0),
            is_inline=data.get("isInline", False),
            content_id=data.get("contentId")
        )

    async def get_emails(
        self,
        mailbox: str,
        since: Optional[datetime] = None,
        top: int = 50,
        select_fields: Optional[List[str]] = None,
        folder: str = "inbox"
    ) -> List[MSGraphEmail]:
        """
        Fetch emails from a mailbox.

        Args:
            mailbox: Email address of the mailbox
            since: Only fetch emails received after this time
            top: Maximum number of emails to fetch
            select_fields: Specific fields to select (None = all)
            folder: Mail folder to fetch from (default: inbox)

        Returns:
            List of MSGraphEmail objects
        """
        try:
            # Build query parameters
            params = {
                "$top": min(top, 100),
                "$orderby": "receivedDateTime desc"
            }

            # Select specific fields for performance
            if select_fields:
                params["$select"] = ",".join(select_fields)
            else:
                params["$select"] = (
                    "id,conversationId,subject,from,receivedDateTime,bodyPreview,"
                    "body,importance,isRead,hasAttachments,toRecipients,ccRecipients,"
                    "categories,internetMessageId,parentFolderId"
                )

            # Filter by date if specified
            if since:
                since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
                params["$filter"] = f"receivedDateTime ge {since_str}"

            endpoint = f"/users/{mailbox}/mailFolders/{folder}/messages"
            data = await self._api_request("GET", endpoint, params=params)

            emails = []
            for item in data.get("value", []):
                try:
                    email = self._parse_email(item)
                    emails.append(email)
                except Exception as e:
                    logger.warning(f"Failed to parse email: {e}")
                    continue

            logger.info(f"Fetched {len(emails)} emails from {mailbox}")
            return emails

        except Exception as e:
            logger.error(f"MS Graph get_emails error for {mailbox}: {e}")
            return []

    async def get_unread_ids(
        self,
        mailbox: str,
        folder: str = "inbox",
        max_pages: int = 25,
        page_size: int = 200,
    ) -> Optional[set]:
        """Return the set of message ids currently UNREAD in `folder`.

        Used to reconcile local read state: anything marked unread locally but
        absent from this set has since been read, moved, or deleted upstream.

        Returns None on failure — callers must treat that as "unknown" and skip
        reconciliation, never as "nothing is unread" (which would mass-mark the
        whole mailbox as read).
        """
        try:
            unread: set = set()
            for page in range(max_pages):
                params = {
                    "$top": page_size,
                    "$skip": page * page_size,
                    "$select": "id",
                    "$filter": "isRead eq false",
                }
                endpoint = f"/users/{mailbox}/mailFolders/{folder}/messages"
                data = await self._api_request("GET", endpoint, params=params)
                items = data.get("value", [])
                for item in items:
                    if item.get("id"):
                        unread.add(item["id"])
                if len(items) < page_size:
                    break
            logger.info(f"{mailbox}: {len(unread)} unread in {folder} per Graph")
            return unread
        except Exception as e:
            logger.error(f"MS Graph get_unread_ids error for {mailbox}: {e}")
            return None

    async def get_email_by_id(self, mailbox: str, message_id: str) -> Optional[MSGraphEmail]:
        """
        Get a specific email by ID.

        Args:
            mailbox: Email address of the mailbox
            message_id: Graph message ID

        Returns:
            MSGraphEmail object or None
        """
        try:
            endpoint = f"/users/{mailbox}/messages/{message_id}"
            data = await self._api_request("GET", endpoint)
            return self._parse_email(data)
        except Exception as e:
            logger.error(f"MS Graph get_email_by_id error: {e}")
            return None

    async def get_attachments(self, mailbox: str, message_id: str) -> List[MSGraphAttachment]:
        """
        Get attachments for an email.

        Args:
            mailbox: Email address of the mailbox
            message_id: Graph message ID

        Returns:
            List of MSGraphAttachment objects
        """
        try:
            endpoint = f"/users/{mailbox}/messages/{message_id}/attachments"
            params = {"$select": "id,name,contentType,size,isInline"}
            data = await self._api_request("GET", endpoint, params=params)

            attachments = []
            for item in data.get("value", []):
                if item.get("@odata.type") == "#microsoft.graph.fileAttachment":
                    attachments.append(self._parse_attachment(item))

            return attachments
        except Exception as e:
            logger.error(f"MS Graph get_attachments error: {e}")
            return []

    async def download_attachment(
        self,
        mailbox: str,
        message_id: str,
        attachment_id: str
    ) -> Optional[bytes]:
        """
        Download an attachment's content.

        Args:
            mailbox: Email address of the mailbox
            message_id: Graph message ID
            attachment_id: Attachment ID

        Returns:
            Attachment content as bytes, or None on error
        """
        try:
            endpoint = f"/users/{mailbox}/messages/{message_id}/attachments/{attachment_id}"
            data = await self._api_request("GET", endpoint)

            # For file attachments, content is base64 encoded
            content_bytes = data.get("contentBytes")
            if content_bytes:
                import base64
                return base64.b64decode(content_bytes)

            return None
        except Exception as e:
            logger.error(f"MS Graph download_attachment error: {e}")
            return None

    async def mark_as_read(self, mailbox: str, message_id: str, is_read: bool = True) -> bool:
        """
        Mark an email as read/unread.

        Args:
            mailbox: Email address of the mailbox
            message_id: Graph message ID
            is_read: True to mark as read, False for unread

        Returns:
            True on success
        """
        try:
            endpoint = f"/users/{mailbox}/messages/{message_id}"
            await self._api_request("PATCH", endpoint, json_body={"isRead": is_read})
            return True
        except Exception as e:
            logger.error(f"MS Graph mark_as_read error: {e}")
            return False

    async def get_mailbox_folders(self, mailbox: str) -> List[Dict[str, Any]]:
        """Get list of mail folders in a mailbox."""
        try:
            endpoint = f"/users/{mailbox}/mailFolders"
            params = {"$select": "id,displayName,totalItemCount,unreadItemCount"}
            data = await self._api_request("GET", endpoint, params=params)
            return data.get("value", [])
        except Exception as e:
            logger.error(f"MS Graph get_mailbox_folders error: {e}")
            return []

    async def sync_all_mailboxes(
        self,
        since: Optional[datetime] = None,
        top_per_mailbox: int = 50
    ) -> Dict[str, List[MSGraphEmail]]:
        """
        Sync emails from all configured mailboxes.

        Args:
            since: Only fetch emails received after this time
            top_per_mailbox: Maximum emails per mailbox

        Returns:
            Dict mapping mailbox address to list of emails
        """
        results = {}
        for mailbox in self.mailboxes:
            emails = await self.get_emails(mailbox, since=since, top=top_per_mailbox)
            results[mailbox] = emails
        return results


# RiskNinja attachment detection patterns
RISKNINJA_PATTERNS = [
    re.compile(r"certificate.*insurance", re.IGNORECASE),
    re.compile(r"\bcoi\b", re.IGNORECASE),  # Certificate of Insurance
    re.compile(r"policy.*number", re.IGNORECASE),
    re.compile(r"acord.*form", re.IGNORECASE),
    re.compile(r"coverage.*proof", re.IGNORECASE),
    re.compile(r"endorsement", re.IGNORECASE),
    re.compile(r"insurance.*certificate", re.IGNORECASE),
    re.compile(r"proof.*coverage", re.IGNORECASE),
    re.compile(r"liability.*insurance", re.IGNORECASE),
    re.compile(r"workers.*comp", re.IGNORECASE),
    re.compile(r"general.*liability", re.IGNORECASE),
    re.compile(r"auto.*insurance", re.IGNORECASE),
    re.compile(r"umbrella.*policy", re.IGNORECASE),
]


def is_riskninja_relevant(filename: str, email_subject: str = "", email_body: str = "") -> bool:
    """
    Detect if an attachment is likely RiskNinja-relevant (insurance documents).

    Args:
        filename: Attachment filename
        email_subject: Email subject line
        email_body: Email body text

    Returns:
        True if the content appears to be insurance-related
    """
    combined_text = f"{filename} {email_subject} {email_body}"

    for pattern in RISKNINJA_PATTERNS:
        if pattern.search(combined_text):
            return True

    # Check for common insurance document extensions with relevant names
    lower_filename = filename.lower()
    lower_subject = email_subject.lower()

    # Check for RiskNinja in filename or subject
    if "riskninja" in lower_filename.replace(" ", "").replace("-", "").replace("_", ""):
        return True
    if "risk ninja" in lower_filename or "risk-ninja" in lower_filename or "risk_ninja" in lower_filename:
        return True
    if "riskninja" in lower_subject.replace(" ", "").replace("-", "").replace("_", ""):
        return True

    if lower_filename.endswith((".pdf", ".doc", ".docx")):
        insurance_keywords = ["coi", "certificate", "insurance", "policy", "acord", "coverage", "endorsement", "binder"]
        for keyword in insurance_keywords:
            if keyword in lower_filename:
                return True

    return False


# Singleton instance - initialized lazily
_msgraph_service: Optional[MSGraphService] = None


def get_msgraph_service() -> MSGraphService:
    """Get or create the MSGraph service singleton"""
    global _msgraph_service

    if _msgraph_service is None:
        _msgraph_service = MSGraphService(
            client_id=settings.msgraph_client_id,
            client_secret=settings.msgraph_client_secret,
            tenant_id=settings.msgraph_tenant_id,
            mailboxes=settings.msgraph_mailboxes
        )

    return _msgraph_service
