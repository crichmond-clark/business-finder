from fastapi import FastAPI
from sqladmin import Admin

from business_finder.admin import LeadAdmin, ScanAdmin
from business_finder.database import engine
from business_finder.exports import router as exports_router

app = FastAPI(title="Business Lead Finder")
app.include_router(exports_router)

admin = Admin(app, engine)
admin.add_view(ScanAdmin)
admin.add_view(LeadAdmin)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
