from dataclasses import dataclass

from business_finder.models import Priority, WebsiteStatus


@dataclass(frozen=True)
class LeadScore:
    score: int
    priority: str


WEBSITE_POINTS = {
    WebsiteStatus.NO_SITE: 45,
    WebsiteStatus.BROKEN: 40,
    WebsiteStatus.SOCIAL_ONLY: 35,
    WebsiteStatus.THIRD_PARTY_PLATFORM: 32,
    WebsiteStatus.UNKNOWN: 15,
    WebsiteStatus.LIVE: 0,
}


def priority_for_score(score: int, business_status: str | None = None) -> str:
    if business_status == "CLOSED_PERMANENTLY":
        return Priority.SKIP
    if score >= 70:
        return Priority.HIGH
    if score >= 40:
        return Priority.MEDIUM
    if score >= 1:
        return Priority.LOW
    return Priority.SKIP


def score_lead_data(
    *,
    website_status: str,
    business_status: str | None,
    rating: float | None,
    review_count: int | None,
    phone: str | None,
    address: str | None,
) -> LeadScore:
    if business_status == "CLOSED_PERMANENTLY":
        return LeadScore(score=0, priority=Priority.SKIP)

    score = WEBSITE_POINTS.get(website_status, WEBSITE_POINTS[WebsiteStatus.UNKNOWN])
    if review_count:
        if review_count >= 50:
            score += 20
        elif review_count >= 10:
            score += 12
        elif review_count >= 3:
            score += 6
    if rating and rating >= 4.0:
        score += 10
    elif rating and rating >= 3.0:
        score += 5
    if phone:
        score += 10
    if address:
        score += 5
    score = min(score, 100)
    return LeadScore(score=score, priority=priority_for_score(score, business_status))


def score_lead(lead) -> LeadScore:
    return score_lead_data(
        website_status=lead.website_status,
        business_status=lead.business_status,
        rating=lead.rating,
        review_count=lead.review_count,
        phone=lead.phone,
        address=lead.address,
    )
