"""Builds 2 new slides for the developer-onboarding guide
(docs/dev-reference/developer-onboarding/guide.html): a high-level "what
runs where" deployment topology (same visual grammar as the user's AWS
reference screenshot - zone bands, numbered flow, DEPLOYABLE badges - but
every box/label is this project's own real, verified infrastructure, not
the reference's ECS/Cognito/ElastiCache/ALB/CloudFront+WAF one), and a
low-level "deploy pipelines, visually" companion covering the one
automated pipeline (hrb-chatbot) plus everything that is NOT automated
today (the Lambda ingestion path, the sibling hrb-lms-mcp service, the UI).

Grounded in (all read in full before writing this):
docs/agent-reference/RAG-ROADMAP.md Phase 88/89/91/94/117/118,
docs/agent-reference/BACKLOG.md's resolved HRB_LMS_MCP_URL entry,
docs/dev-reference/developer-onboarding/guide.html,
docs/dev-reference/database/db-model-overview.html, .env.example's Redis
block. Appends to whatever the deck already has (28 slides before this
script runs). Run as: python scripts/build_deployment_view_slide.py"""

import os

from pptx.dml.color import RGBColor

from deck_common import (
    AGENT_FILL, AGENT_LINE, TOOL_FILL, TOOL_LINE, STORE_FILL, STORE_LINE,
    EMPLOYEE_FILL, EMPLOYEE_LINE, SLATE_DARK, SLATE_MED, PANEL_BG,
    new_slide, add_header, add_section_label, legend_chip, box, swim_lane,
    bullet_panel, even_columns, save_deck,
)
from pptx import Presentation

DST = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11.pptx"
DST_TMP = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11_wip.pptx"
SRC = DST if os.path.exists(DST) else DST_TMP

PANEL_BORDER = RGBColor(0xC7, 0xD2, 0xDE)
EXTERNAL_FILL, EXTERNAL_LINE = RGBColor(0xFD, 0xF1, 0xE3), RGBColor(0xE3, 0xB5, 0x74)


def zone_band(slide, label_text, panel_y, boxes, panel_h):
    """One single-row zone band (Users / Edge / AWS / External) - a plain
    swim_lane() call with an empty bottom_row, so no store row/arrows get
    drawn, just the labeled band + one row of boxes."""
    return swim_lane(slide, label_text, panel_y, boxes, [], panel_h=panel_h)


def build_deployment_view(prs):
    slide = new_slide(prs)
    add_header(
        slide, "Deployment View: What Runs Where",
        "4 real deployables across 2 AWS App Runner services, 1 Lambda, 1 static site \u2013 no ECS/ALB/CloudFront+WAF/Cognito",
    )
    legend_chip(slide, 7200000, 660400, 1500000, TOOL_FILL, TOOL_LINE, "AWS compute")
    legend_chip(slide, 8800000, 660400, 1300000, AGENT_FILL, AGENT_LINE, "AWS data-plane")
    legend_chip(slide, 10200000, 660400, 1900000, EXTERNAL_FILL, EXTERNAL_LINE, "External managed service")

    y = 870000

    xs, bw = even_columns(227000, 11938000, 1)
    users = [(xs[0], bw, EMPLOYEE_FILL, EMPLOYEE_LINE,
              "\u2460 Browser (employee / HR user)",
              "hits the hosted hrb_chatbot_ui React app, and/or calls the API directly (Postman/curl) \u2013 no separate mobile client",
              SLATE_DARK, SLATE_MED)]
    y = zone_band(slide, "Users", y, users, panel_h=840000) + 100000

    xs, bw = even_columns(227000, 11938000, 3)
    edge = [
        (xs[0], bw, TOOL_FILL, TOOL_LINE, "\u2461 hrb-chatbot.rvsree.dev",
         "Route 53 CNAME straight to App Runner's own TLS endpoint \u2013 no ALB, no CloudFront, no WAF in front of the API itself (Phase 94)",
         SLATE_DARK, SLATE_MED),
        (xs[1], bw, TOOL_FILL, TOOL_LINE, "\u2462 DEPLOYABLE 4 \u2013 hrb-chatbot-ui.rvsree.dev",
         "the only CloudFront in this system \u2013 distribution in front of S3 bucket hrb-chatbot-ui-rvsree, the built React static site (Phase 117)",
         SLATE_DARK, SLATE_MED),
        (xs[2], bw, TOOL_FILL, TOOL_LINE, "\u2463 hrb-lms-mcp.rvsree.dev",
         "separate custom domain for the sibling hrb_lms_mcp service, same ACM/Route53 pattern (Phase 118)",
         SLATE_DARK, SLATE_MED),
    ]
    y = zone_band(slide, "Edge / DNS \u2013 Route 53 + ACM, registered under rvsree.dev", y, edge, panel_h=840000) + 100000

    xs, bw = even_columns(227000, 11938000, 4)
    aws = [
        (xs[0], bw, TOOL_FILL, TOOL_LINE, "DEPLOYABLE 1 \u2013 App Runner: hrb-chatbot",
         "this repo's FastAPI RAG backend \u2013 AutoDeploymentsEnabled=false, deploy.yml redeploys on every push to master",
         SLATE_DARK, SLATE_MED),
        (xs[1], bw, TOOL_FILL, TOOL_LINE, "DEPLOYABLE 2 \u2013 App Runner: hrb-lms-mcp",
         "sibling hrb_lms_mcp repo \u2013 OAuth2 client-credentials from hrb-chatbot (Phase 53), deployed/wired Phase 118, its own deploy.yml",
         SLATE_DARK, SLATE_MED),
        (xs[2], bw, TOOL_FILL, TOOL_LINE, "DEPLOYABLE 3 \u2013 Lambda: hrb-chatbot-index-document",
         "async ingestion handler (Phase 88) \u2013 SQS-triggered, no CI/CD automation at all: every deploy is a manual update-function-code",
         SLATE_DARK, SLATE_MED),
        (xs[3], bw, AGENT_FILL, AGENT_LINE, "\u2464 S3 + SQS",
         "hrb-chatbot-kb-uploads bucket \u2192 ObjectCreated \u2192 hrb-chatbot-ingest-queue/-dlq \u2192 the Lambda above \u2013 additive alongside the still-live synchronous upload (Phase 89)",
         SLATE_DARK, SLATE_MED),
    ]
    y = zone_band(slide, "AWS \u2013 the real deployables (us-east-1, account 418884736369)", y, aws, panel_h=870000) + 100000

    xs, bw = even_columns(227000, 11938000, 5)
    external = [
        (xs[0], bw, EXTERNAL_FILL, EXTERNAL_LINE, "\u2465 Pinecone", "RAG_VECTOR_DB=pinecone, live \u2013 the vector store for document chunks", SLATE_DARK, SLATE_MED),
        (xs[1], bw, EXTERNAL_FILL, EXTERNAL_LINE, "\u2466 Neon Postgres (hr_chatbot db)", "shared w/ hrb_lms_mcp/hrb_emp_assist \u2013 this project's own schemas + hrb_lms_mcp's hrb_emp_lms/hrb_lms_mcp_auth (Phase 118). RAG document metadata itself is still sqlite in prod \u2013 a separate thing.", SLATE_DARK, SLATE_MED),
        (xs[2], bw, EXTERNAL_FILL, EXTERNAL_LINE, "\u2467 Upstash Redis", "rediss:// \u2013 answer cache, embedding cache, rate limiter (Phase 84); Upstash over ElastiCache since App Runner isn't VPC-peered", SLATE_DARK, SLATE_MED),
        (xs[3], bw, EXTERNAL_FILL, EXTERNAL_LINE, "\u2468 OpenAI / Anthropic / OpenRouter", "LLM + embedding providers, selected via the LlmProvider enum", SLATE_DARK, SLATE_MED),
        (xs[4], bw, EXTERNAL_FILL, EXTERNAL_LINE, "LangSmith", "optional tracing, hrb_chatbot_service_prod project, on when LANGSMITH_ENABLED=true", SLATE_DARK, SLATE_MED),
    ]
    y = zone_band(slide, "External Services \u2013 managed, outside AWS, reached over the open internet", y, external, panel_h=840000) + 120000

    bullet_panel(
        slide, 227000, y, 11938000, 980000, PANEL_BG, PANEL_BORDER,
        "Real system vs. the reference screenshot's own architecture",
        [
            "No ECS Fargate, no ALB, no CloudFront+WAF in front of the API, no Cognito, no ElastiCache, no ingestion-worker consuming its own queue as a long-lived process \u2013 this system uses App Runner (2 services) + 1 Lambda + 1 static S3/CloudFront site instead.",
            "Flagged, not silently resolved: docs/agent-reference/AWS-DEVOPS-RUNBOOK.md's top-level \u201cS3/Lambda not implemented at all\u201d line is stale \u2013 Phase 88/89 built and verified the S3\u2192SQS\u2192Lambda path live on AWS, 2026-10-06.",
            "develop has no deploy target today (an open, un-made decision) \u2013 only master arms deploy.yml for hrb-chatbot.",
        ],
        heading_color=SLATE_DARK, bullet_color=SLATE_MED,
    )


def build_deploy_pipelines(prs):
    slide = new_slide(prs)
    add_header(
        slide, "Low-Level: The Deploy Pipelines, Visually",
        "companion to Section 3's prose \u2013 1 real CI/CD pipeline, everything else still manual or a separate repo's own",
    )
    add_section_label(slide, "Layered swim lanes - process (top row) vs. the real store/service each step pushes to (bottom row)")
    legend_chip(slide, 9000000, 660400, 1500000, EMPLOYEE_FILL, EMPLOYEE_LINE, "Developer / CI")
    legend_chip(slide, 10600000, 660400, 1500000, AGENT_FILL, AGENT_LINE, "AWS step")

    xs, bw = even_columns(227000, 11938000, 6)
    top1 = [
        (xs[0], bw, EMPLOYEE_FILL, EMPLOYEE_LINE, "git push to master", "arms .github/workflows/deploy.yml \u2013 feature/develop branches never trigger it", SLATE_DARK, SLATE_MED),
        (xs[1], bw, AGENT_FILL, AGENT_LINE, "ci.yml gates", "import sanity, pytest + 45% coverage floor, bandit -ll \u2013 all blocking", SLATE_DARK, SLATE_MED),
        (xs[2], bw, AGENT_FILL, AGENT_LINE, "docker buildx build", "--provenance=false --sbom=false, oci-mediatypes=false \u2013 App Runner silently refuses to start the container without these", SLATE_DARK, SLATE_MED),
        (xs[3], bw, AGENT_FILL, AGENT_LINE, "push :latest to ECR", "hrb-chatbot repo \u2013 no :<sha> tag today, so there's no tagged-image rollback shortcut", SLATE_DARK, SLATE_MED),
        (xs[4], bw, AGENT_FILL, AGENT_LINE, "aws apprunner start-deployment", "explicit call \u2013 AutoDeploymentsEnabled=false, a new ECR push alone does nothing", SLATE_DARK, SLATE_MED),
        (xs[5], bw, AGENT_FILL, AGENT_LINE, "poll + smoke test", "poll Service.Status for RUNNING, then curl --fail /ping on the live URL", SLATE_DARK, SLATE_MED),
    ]
    bottom1 = [
        (xs[2], (xs[3] + bw) - xs[2], "ECR", "418884736369.dkr.ecr.../hrb-chatbot"),
        (xs[4], (xs[5] + bw) - xs[4], "App Runner", "hrb-chatbot, 1 running service"),
    ]
    y = swim_lane(slide, "1 \u00b7 hrb-chatbot \u2013 the one real, automated CI/CD pipeline", 870000, top1, bottom1)

    xs2, bw2 = even_columns(227000, 11938000, 3)
    top2 = [
        (xs2[0], bw2, TOOL_FILL, TOOL_LINE, "Lambda ingestion path \u2013 manual only",
         "docker buildx build Dockerfile.lambda \u2192 push ECR hrb-chatbot-lambda \u2192 aws lambda update-function-code by hand \u2013 deploy.yml never touches this (confirmed Phase 89)",
         SLATE_DARK, SLATE_MED),
        (xs2[1], bw2, TOOL_FILL, TOOL_LINE, "hrb-lms-mcp \u2013 its own CI/CD",
         "separate hrb_lms_mcp repo, its own deploy.yml, its own ECR repo \u2013 same AutoDeploymentsEnabled=false pattern (Phase 118)",
         SLATE_DARK, SLATE_MED),
        (xs2[2], bw2, TOOL_FILL, TOOL_LINE, "hrb_chatbot_ui \u2013 static site deploy",
         "separate repo builds the React app \u2192 S3 bucket hrb-chatbot-ui-rvsree \u2192 CloudFront \u2013 exact build/sync steps not confirmed from this repo, flagged not guessed",
         SLATE_DARK, SLATE_MED),
    ]
    bottom2 = [
        (xs2[0], bw2, "ECR + Lambda", "hrb-chatbot-lambda \u2192 hrb-chatbot-index-document"),
        (xs2[1], bw2, "App Runner", "hrb-lms-mcp, separate service"),
        (xs2[2], bw2, "S3 + CloudFront", "hrb-chatbot-ui-rvsree"),
    ]
    y2 = swim_lane(slide, "2 \u00b7 Everything else \u2013 manual or a separate repo's own automation", y + 100000, top2, bottom2)

    bullet_panel(
        slide, 227000, y2 + 150000, 11938000, 780000, PANEL_BG, PANEL_BORDER,
        "The one norm that sits above both lanes",
        [
            "Nothing gets pushed/deployed/synced to AWS without the developer's own local review and explicit go-ahead first (CLAUDE.md, 2026-10-14) \u2013 every box above is meant to be run and verified locally before git push to master arms lane 1.",
        ],
        heading_color=SLATE_DARK, bullet_color=SLATE_MED,
    )


def main():
    prs = Presentation(SRC)
    build_deployment_view(prs)
    build_deploy_pipelines(prs)
    save_deck(prs, DST, DST_TMP)


if __name__ == "__main__":
    main()
