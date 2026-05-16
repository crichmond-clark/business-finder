from business_finder.scorer import score_lead_data


def test_closed_business_is_skip():
    result = score_lead_data(
        website_status="no_site",
        business_status="CLOSED_PERMANENTLY",
        rating=5,
        review_count=100,
        phone="01752 000000",
        address="Plymouth",
    )
    assert result.score == 0
    assert result.priority == "skip"


def test_strong_no_site_lead_is_high_priority():
    result = score_lead_data(
        website_status="no_site",
        business_status="OPERATIONAL",
        rating=4.5,
        review_count=60,
        phone="01752 000000",
        address="Plymouth",
    )
    assert result.score >= 70
    assert result.priority == "high"


def test_live_site_low_signal_is_low_priority():
    result = score_lead_data(
        website_status="live",
        business_status="OPERATIONAL",
        rating=None,
        review_count=None,
        phone=None,
        address=None,
    )
    assert result.priority == "skip"


def test_broken_site_with_some_reviews_is_medium_or_high():
    result = score_lead_data(
        website_status="broken",
        business_status="OPERATIONAL",
        rating=3.5,
        review_count=12,
        phone=None,
        address=None,
    )
    assert result.score == 57
    assert result.priority == "medium"
