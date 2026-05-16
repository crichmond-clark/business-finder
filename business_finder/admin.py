from sqladmin import ModelView
from sqladmin.filters import AllUniqueStringValuesFilter, ForeignKeyFilter

from business_finder.models import Lead, Scan


class ScanAdmin(ModelView, model=Scan):
    name = "Scan"
    name_plural = "Scans"
    column_list = [Scan.id, Scan.query, Scan.city, Scan.results_count, Scan.high_priority_count, Scan.created_at]
    column_details_list = [
        Scan.id,
        Scan.query,
        Scan.category,
        Scan.included_type,
        Scan.city,
        Scan.country_code,
        Scan.max_pages,
        Scan.results_count,
        Scan.high_priority_count,
        Scan.created_at,
    ]
    column_sortable_list = [Scan.id, Scan.created_at, Scan.results_count, Scan.high_priority_count]


class LeadAdmin(ModelView, model=Lead):
    name = "Lead"
    name_plural = "Leads"
    can_export = True
    column_list = [
        Lead.name,
        Lead.website_url,
        Lead.website_status,
        Lead.priority,
        Lead.score,
        Lead.rating,
        Lead.review_count,
        Lead.phone,
        Lead.email,
        Lead.outreach_status,
    ]
    column_searchable_list = [Lead.name, Lead.address, Lead.phone, Lead.email]
    column_filters = [
        AllUniqueStringValuesFilter(Lead.website_status),
        AllUniqueStringValuesFilter(Lead.priority),
        AllUniqueStringValuesFilter(Lead.outreach_status),
        AllUniqueStringValuesFilter(Lead.business_status),
        ForeignKeyFilter(Lead.scan_id, Scan.query),
    ]
    column_sortable_list = [Lead.priority, Lead.score, Lead.rating, Lead.review_count, Lead.created_at]
    column_default_sort = [(Lead.priority, True), (Lead.score, True)]
    form_edit_rules = ["email", "email_source", "notes", "outreach_status"]
