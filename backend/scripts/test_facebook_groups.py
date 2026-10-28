from django.core.exceptions import ValidationError
from django.db import transaction
from modules.pipelines.models import Pipeline
from modules.facebook_groups.models import FacebookGroup
pipeline = Pipeline.objects.first()
assert pipeline is not None, "Pipeline not found"
initial_count = FacebookGroup.objects.count()
with transaction.atomic():
    group = FacebookGroup.objects.create(
        pipeline=pipeline,
        name="Vietnam Linux Community",
        group_url=(
            "https://m.facebook.com/groups/"
            "vietnamlinuxcommunity/?ref=share"
        ),
    )
    assert group.group_key == "vietnamlinuxcommunity"
    assert group.group_url == (
        "https://www.facebook.com/groups/"
        "vietnamlinuxcommunity/"
    )
    assert group.is_enabled is True
    assert group.verification_status == "unknown"
    print("GROUP CREATE: PASS")
    print("URL NORMALIZATION: PASS")
    print("DEFAULT STATUS: UNKNOWN")
    try:
        FacebookGroup.objects.create(
            pipeline=pipeline,
            name="Duplicate Group",
            group_url=(
                "https://www.facebook.com/groups/"
                "VietnamLinuxCommunity/"
            ),
        )
    except ValidationError:
        print("DUPLICATE GROUP: BLOCKED")
    else:
        raise AssertionError(
            "Duplicate Group was not blocked"
        )
    try:
        FacebookGroup.objects.create(
            pipeline=pipeline,
            name="Invalid Group",
            group_url="https://example.com/groups/test/",
        )
    except ValidationError:
        print("INVALID DOMAIN: BLOCKED")
    else:
        raise AssertionError(
            "Invalid domain was accepted"
        )
    unicode_group = FacebookGroup.objects.create(
        pipeline=pipeline,
        name="Cà phê",
        group_url="https://www.facebook.com/groups/cà-phê/",
    )
    assert unicode_group.group_key == "cà-phê"
    print("UNICODE GROUP URL: PASS")
    transaction.set_rollback(True)
assert FacebookGroup.objects.count() == initial_count
print("DATABASE CHANGES: ROLLED BACK")
print("FACEBOOK GROUPS TEST: PASSED")
