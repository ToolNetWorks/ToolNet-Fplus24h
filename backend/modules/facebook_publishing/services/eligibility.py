"""Group eligibility check for the Facebook Publishing Worker.

Verifies that an Account is authorized to post anonymously to a Group.
Does NOT auto-join Groups. Does NOT bypass any checkpoints.
"""
from dataclasses import dataclass

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.publishing.scheduler_models import (
    AccountGroupEligibility, GroupHealth,
)


@dataclass(frozen=True)
class GroupEligibilityResult:
    account_id: str
    group_id: str
    is_eligible: bool
    can_post_anonymous: bool
    membership_status: str
    reason_code: str
    evidence_note: str
    is_group_active: bool


def check_group_eligibility(*, pipeline_id, account_id, group_id):
    """Check if the Account can post anonymously to the Group.

    Returns a GroupEligibilityResult with the decision.
    - Anonymous posting is REQUIRED.
    - Group membership can be ANY (member or non-member).
    - Permission must be VERIFIED (not just inferred).
    - Does NOT auto-join Groups.
    - Does NOT bypass CAPTCHA, checkpoint, or access permissions.
    """
    account = FacebookAccount.objects.filter(
        pk=account_id, pipeline_id=pipeline_id,
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED,
    ).first()
    if account is None:
        return GroupEligibilityResult(
            account_id=str(account_id), group_id=str(group_id),
            is_eligible=False, can_post_anonymous=False,
            membership_status='unknown',
            reason_code='ACCOUNT_NOT_CONNECTED',
            evidence_note='', is_group_active=False,
        )

    group = FacebookGroup.objects.filter(
        pk=group_id, pipeline_id=pipeline_id, is_enabled=True,
    ).first()
    if group is None:
        return GroupEligibilityResult(
            account_id=str(account_id), group_id=str(group_id),
            is_eligible=False, can_post_anonymous=False,
            membership_status='unknown',
            reason_code='GROUP_DISABLED_OR_NOT_FOUND',
            evidence_note='', is_group_active=False,
        )

    health = GroupHealth.objects.filter(
        pipeline_id=pipeline_id, group_id=group_id,
    ).first()
    is_group_active = (
        health is None or health.state == GroupHealth.State.ACTIVE
    )
    if not is_group_active:
        return GroupEligibilityResult(
            account_id=str(account_id), group_id=str(group_id),
            is_eligible=False, can_post_anonymous=False,
            membership_status='unknown' if health is None else health.evidence_note,
            reason_code='GROUP_HEALTH_' + (health.state.upper() if health else 'UNKNOWN'),
            evidence_note=health.evidence_note if health else '',
            is_group_active=False,
        )

    eligibility = AccountGroupEligibility.objects.filter(
        pipeline_id=pipeline_id, account_id=account_id, group_id=group_id,
        state=AccountGroupEligibility.State.VERIFIED,
    ).first()

    if eligibility is None:
        return GroupEligibilityResult(
            account_id=str(account_id), group_id=str(group_id),
            is_eligible=False, can_post_anonymous=False,
            membership_status='unknown',
            reason_code='NO_VERIFIED_ELIGIBILITY',
            evidence_note='',
            is_group_active=is_group_active,
        )

    if not eligibility.can_post_anonymous:
        return GroupEligibilityResult(
            account_id=str(account_id), group_id=str(group_id),
            is_eligible=False, can_post_anonymous=False,
            membership_status='member' if not eligibility.can_post_nonmember else 'unknown',
            reason_code='CANNOT_POST_ANONYMOUSLY',
            evidence_note=eligibility.evidence_note,
            is_group_active=is_group_active,
        )

    # Membership status is informational only. Anonymous posting works
    # regardless of member/non-member status.
    membership_status = 'member' if not eligibility.can_post_nonmember else 'unknown'

    return GroupEligibilityResult(
        account_id=str(account_id), group_id=str(group_id),
        is_eligible=True, can_post_anonymous=True,
        membership_status=membership_status,
        reason_code='VERIFIED',
        evidence_note=eligibility.evidence_note,
        is_group_active=is_group_active,
    )
