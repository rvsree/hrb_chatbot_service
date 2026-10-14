"""Builds slide 24: the real CI/CD + deployment pipeline (App Runner, not
EC2/ECS/K8s) and the real observability destinations - grounded directly in
docs/dev-reference/deployment-guide/01-deployment-aws.html's own content
(.github/workflows/deploy.yml's real steps, confirmed App Runner has no
AutoDeploymentsEnabled, the 2 real CloudWatch log groups, LangSmith already
live in production per service-config.json). Same swim-lane template as
slides 18-23. Run as: python scripts/build_deployment_slide.py"""

import os

from pptx import Presentation
from pptx.dml.color import RGBColor

from deck_common import (
    EMPLOYEE_FILL, EMPLOYEE_LINE, AGENT_FILL, AGENT_LINE, TOOL_FILL, TOOL_LINE,
    SLATE_DARK, SLATE_MED, PANEL_BG,
    new_slide, add_header, add_section_label, legend_chip, swim_lane, bullet_panel,
    even_columns, save_deck,
)

DST = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11.pptx"
DST_TMP = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11_wip.pptx"
SRC = DST if os.path.exists(DST) else DST_TMP

PANEL_BORDER = RGBColor(0xC7, 0xD2, 0xDE)


def add_legend(slide):
    legend_chip(slide, 7800000, 660400, 700000, EMPLOYEE_FILL, EMPLOYEE_LINE, "Developer")
    legend_chip(slide, 8550000, 660400, 900000, AGENT_FILL, AGENT_LINE, "GitHub Actions")
    legend_chip(slide, 9500000, 660400, 1100000, TOOL_FILL, TOOL_LINE, "AWS service")
    legend_chip(slide, 10650000, 660400, 900000, TOOL_FILL, TOOL_LINE, "Observability")


def main():
    prs = Presentation(SRC)
    slide = new_slide(prs)
    add_header(
        slide,
        "Real Deployment: App Runner, Not EC2/ECS/K8s",
        "companion to deployment-guide/01-deployment-aws.html \u00b7 .github/workflows/deploy.yml, confirmed",
    )
    add_section_label(slide, "Layered swim lanes - process (top row) vs. the real stores & services each step touches (bottom row)")
    add_legend(slide)

    xs, bw = even_columns(254000, 11684000, 6)
    top1 = [
        (xs[0], bw, EMPLOYEE_FILL, EMPLOYEE_LINE, "git push to master", "triggers .github/workflows/deploy.yml", SLATE_DARK, SLATE_MED),
        (xs[1], bw, AGENT_FILL, AGENT_LINE, "docker buildx build", "--provenance=false --sbom=false --push \u2013 App Runner silently fails to start without these 2 flags", SLATE_DARK, SLATE_MED),
        (xs[2], bw, AGENT_FILL, AGENT_LINE, "push to ECR", "the container registry \u2013 same role as Nexus/Artifactory, images not jars", SLATE_DARK, SLATE_MED),
        (xs[3], bw, AGENT_FILL, AGENT_LINE, "aws apprunner start-deployment", "explicit trigger \u2013 no AutoDeploymentsEnabled, confirmed Phase 10", SLATE_DARK, SLATE_MED),
        (xs[4], bw, AGENT_FILL, AGENT_LINE, "poll Service.Status", "until RUNNING \u2013 takes a minute or two, not instant", SLATE_DARK, SLATE_MED),
        (xs[5], bw, AGENT_FILL, AGENT_LINE, "smoke test", "curl the live /ping endpoint for a real 200", SLATE_DARK, SLATE_MED),
    ]
    bottom1 = [
        (xs[1], (xs[2] + bw) - xs[1], "ECR", "hrb-chatbot image, versioned by git SHA"),
        (xs[3], (xs[5] + bw) - xs[3], "App Runner", "1 running service \u2013 pulls the new image only on this explicit call"),
    ]
    bottom_y1 = swim_lane(slide, "1 \u00b7 Build & deploy (live) \u2013 the real CI/CD pipeline", 870000, top1, bottom1)

    xs2, bw2 = even_columns(254000, 11684000, 3)
    top2 = [
        (xs2[0], bw2, TOOL_FILL, TOOL_LINE, "Container platform events", "image pulled, deploy started/failed \u2013 the only log if the container never starts at all", SLATE_DARK, SLATE_MED),
        (xs2[1], bw2, TOOL_FILL, TOOL_LINE, "Application stdout", "real FastAPI/uvicorn output \u2013 request logs, exceptions, everything get_logger() writes", SLATE_DARK, SLATE_MED),
        (xs2[2], bw2, TOOL_FILL, TOOL_LINE, "LLM/agent traces", "every RAG pipeline call, already live in production", SLATE_DARK, SLATE_MED),
    ]
    bottom2 = [
        (xs2[0], bw2, "CloudWatch", ".../service log group"),
        (xs2[1], bw2, "CloudWatch", ".../application log group"),
        (xs2[2], bw2, "LangSmith", "LANGSMITH_ENABLED=true, confirmed in the real service-config.json"),
    ]
    bottom_y2 = swim_lane(slide, "2 \u00b7 Observe & verify (live) \u2013 where a real failure actually shows up", 2650000, top2, bottom2)

    bullet_panel(slide, 127000, bottom_y2 + 150000, 11938000, 980000, PANEL_BG, PANEL_BORDER, "Real system vs. the deck's own target-state slides (13-15)", [
        "App Runner, one service \u2013 not the target-state slides' ECS Fargate / multi-service / SQS-worker architecture",
        "No auto-redeploy on a new ECR image \u2013 step 4 (start-deployment) is the only thing that actually triggers a rollout",
        "A container that never starts leaves ONLY the .../service log \u2013 .../application never gets written, confirmed in practice",
    ])

    save_deck(prs, DST, DST_TMP)


if __name__ == "__main__":
    main()
