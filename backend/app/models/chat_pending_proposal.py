"""R01 review remediation (Sara repair plan 2026-09-25): a typed pending-
proposal record, distinct from a completed action.

Before this, "was this a legitimate continuation?" was answered entirely by
`_CHAT_INVOKED_MUTATING_TOOL_NAMES` — the list of mutating tool NAMES this
session actually EXECUTED last turn. That conflates two different things:
"Sara already did X" (a completed action) and "Sara is asking whether to do
X" (a proposal awaiting explicit approval) — and it only ever remembers a
bare tool NAME, not the specific arguments/target that were actually
proposed, so a scoped "yes" ends up re-authorizing "whatever mutating tool
this session touched last turn," not "exactly the one specific thing that
was being asked about."

This mirrors the shape of every OTHER "propose then explicitly approve"
pattern already in this codebase (`workout_adjustment_proposal`,
`soul_change_proposals`, `prompt_proposals` — see
`app/services/workout_command_service.py`'s `_create_proposal`/
`_apply_resolve_proposal` for the canonical version): a durable row with a
status, an expiry, and consume-once semantics. It is intentionally NOT
reused directly — that mechanism is reached through a structured API/UI
action carrying an explicit `proposal_id`, never through free-text chat
continuation — but the row shape (propose → time-boxed pending → consumed
exactly once) is the same idea, scoped down for the chat mutation gate.
"""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import func

from app.db.base import Base


class ChatPendingProposal(Base):
    __tablename__ = "chat_pending_proposal"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    # Chat's own session/conversation identity — a proposal from one
    # conversation must never be consumable by a confirmation typed into a
    # different one.
    conversation_id = Column(String, nullable=False, index=True)
    tool_name = Column(String, nullable=False)
    # The exact tool-call arguments JSON string the model attempted — a
    # scoped "yes" re-executes exactly THIS, not a freshly re-decided call.
    arguments_json = Column(Text, nullable=False)
    # Short human-readable description, for logs/debugging only — never
    # used for matching.
    summary = Column(Text, nullable=True)
    # The human's own turn message that prompted this refusal/proposal.
    # Required so a later consume() for a RECURRING_ESTABLISHING_TOOL can
    # still verify recurring-scope evidence against the message that
    # actually carries it — the confirming "yes" never will, and
    # consuming a proposal must not become a back door around that check
    # (a hypothetical, non-recurring message proposed and refused, then
    # bare-"yes"-confirmed, must still not be enough to create a standing
    # order — see main_simple.py's execute_tool for the actual check).
    source_message = Column(Text, nullable=True)
    # Round 2 (2026-09-26 review): Sara's own FINAL reply text for the
    # turn the refusal happened on — the actual evidence the user was
    # informed at all. Written once, after the turn's reply is finalized
    # (main_simple.py's `_store_conversation_with_timeout`, the single
    # choke point every turn-exit path funnels through) — never at
    # refusal time itself, which is before that text exists. A proposal
    # with no substantive presented_summary is never inserted at all (see
    # chat_proposal_service.propose's MIN_PRESENTED_SUMMARY_CHARS guard),
    # so `status='pending'` already implies this is non-trivial — but the
    # column stays nullable because a pre-migration row (none should ever
    # exist) must not violate a NOT NULL constraint retroactively.
    presented_summary = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending|consumed|expired|superseded
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
