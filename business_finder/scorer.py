from dataclasses import dataclass


@dataclass(frozen=True)
class LeadScore:
    score: int
    priority: str


WEBSITE_POINTS = {
    "no_site": 45,
    "broken": 40,
    "social_only": 35,
    "third_party_platform": 32,
    "unknown": 15,
    "live": 0,
}


def priority_for_score(score: int, business_status: str | None = None) -> str:
    if business_status == "CLOSED_PERMANENTLY":
        return "skip"
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    if score >= 1:
        return "low"
    return "skip"


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
        return LeadScore(score=0, priority="skip")

    score = WEBSITE_POINTS.get(website_status, WEBSITE_POINTS["unknown"])
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
