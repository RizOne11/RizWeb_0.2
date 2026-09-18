from __future__ import annotations

from puma_scouts.category_profiles import assess_category
from puma_scouts.models import IdentityConfidence, Verdict
from puma_scouts.validator_base import *  # noqa: F401,F403
from puma_scouts.validator_base import validate_offer as _base_validate_offer


def validate_offer(mission, offer):
    checked = _base_validate_offer(mission, offer)
    offer_text = " ".join(
        [offer.title, *[f"{key} {value}" for key, value in offer.attributes.items()]]
    )
    category = assess_category(mission, offer_text)

    if category.profile != "generic":
        marker = f"category profile: {category.profile}"
        if marker not in checked.positive_evidence:
            checked.positive_evidence.append(marker)

    if category.conflicts:
        for conflict in category.conflicts:
            if conflict not in checked.conflicts:
                checked.conflicts.append(conflict)
        checked.identity_confidence = IdentityConfidence.CONFLICT
        if checked.verdict == Verdict.PASS:
            checked.verdict = Verdict.CONFLICT
            checked.score = min(checked.score, 0.64)
        return checked

    if category.missing_critical and checked.verdict == Verdict.PASS:
        missing = ", ".join(category.missing_critical)
        marker = f"category critical attributes not confirmed: {missing}"
        if marker not in checked.positive_evidence:
            checked.positive_evidence.append(marker)
        if checked.identity_confidence == IdentityConfidence.CONFIRMED:
            checked.identity_confidence = IdentityConfidence.PROBABLE

    return checked
