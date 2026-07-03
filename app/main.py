import os
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, JSONResponse
from app.routers import dashboard, profile, meal_plan, shopping, stock

app = FastAPI(title="NutriPlan")


app.include_router(dashboard.router)
app.include_router(profile.router)
app.include_router(meal_plan.router)
app.include_router(shopping.router)
app.include_router(stock.router)


@app.get("/debug-env")
def debug_env():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return JSONResponse({
        "ANTHROPIC_API_KEY_set": bool(key),
        "ANTHROPIC_API_KEY_length": len(key),
        "ANTHROPIC_API_KEY_preview": key[:8] + "..." if key else "VACÍO",
    })


@app.get("/")
def root():
    return RedirectResponse("/dashboard", status_code=303)
