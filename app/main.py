from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from app.routers import dashboard, profile, meal_plan, shopping, stock

app = FastAPI(title="NutriPlan")


app.include_router(dashboard.router)
app.include_router(profile.router)
app.include_router(meal_plan.router)
app.include_router(shopping.router)
app.include_router(stock.router)


@app.get("/")
def root():
    return RedirectResponse("/dashboard", status_code=303)
