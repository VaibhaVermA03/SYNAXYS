from fastapi import APIRouter

from app.api.v1 import auth, github, dashboard, health, webhooks, pull_requests, review_rules, reviews, review_actions, repositories, code_search, settings

api_router = APIRouter(prefix="/api/v1")
for r in (health.router, 
          auth.router, 
          github.router, 
          webhooks.router, 
          dashboard.router, 
          pull_requests.router, 
          reviews.router, 
          review_rules.router, 
          review_actions.router, 
          code_search.router, 
          repositories.router, 
          settings.router):
    api_router.include_router(r)
