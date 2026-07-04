import os
import logging
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.routers import dashboard, profile, meal_plan, shopping, stock
from app.routers import auth as auth_router
from app.routers import admin as admin_router
from app.routers import household as household_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

app = FastAPI(title="NutriPlan")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(household_router.router)
app.include_router(dashboard.router)
app.include_router(profile.router)
app.include_router(meal_plan.router)
app.include_router(shopping.router)
app.include_router(stock.router)


@app.on_event("startup")
def create_admin():
    from app.database import SessionLocal
    from app.models.user import User
    from app.services.auth_service import hash_password
    from app.config import settings
    if not settings.admin_email or not settings.admin_password:
        return
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == settings.admin_email.lower()).first()
        if not admin:
            admin = User(
                email=settings.admin_email.lower(),
                hashed_password=hash_password(settings.admin_password),
                role="admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            logging.getLogger(__name__).info(f"Admin user created: {settings.admin_email}")
        elif admin.role != "admin":
            admin.role = "admin"
            db.commit()
    finally:
        db.close()


@app.get("/debug-env")
def debug_env():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return JSONResponse({
        "ANTHROPIC_API_KEY_set": bool(key),
        "ANTHROPIC_API_KEY_length": len(key),
        "ANTHROPIC_API_KEY_preview": key[:8] + "..." if key else "VACIO",
    })


@app.get("/")
def root():
    return RedirectResponse("/dashboard", status_code=303)
