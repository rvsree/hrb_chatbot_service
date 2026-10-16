#!/usr/bin/env python
"""Phase 187 - one-time migration: parses the real 38 cards out of
prototype-new-format.html and agentic-research-systems.html's own DOM
(both already in the 7-part format) and inserts them as real
interview_qa_cards rows. The HTML's own already-written content is the
source - nothing here is rewritten by hand. Run as:
python -m scripts.migrate_interview_qa_to_db

Already run successfully against both local dev and production Postgres
(38/38 cards each, Phase 187/Phase 190) - kept only as a historical
record of how the DB got seeded. Both source HTML files were deleted
2026-10-16 now that the DB is the real source of truth, so re-running
this script will fail with FileNotFoundError - that's expected, not a
bug to fix."""

import asyncio
import re

from bs4 import BeautifulSoup, Tag

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway

FILES = [
    ("docs/dev-reference/interview-faqs/prototype-new-format.html", None),
    ("docs/dev-reference/interview-faqs/agentic-research-systems.html", "Agentic Research Systems"),
]


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    return text or None


def _part_text(card: Tag, label: str) -> str | None:
    """Finds a .part div whose .part-label text matches, returns the text
    after the label (everything else in that .part div)."""
    for part in card.select(".part"):
        label_node = part.find(class_="part-label")
        if label_node and label_node.get_text(strip=True).lower().startswith(label.lower()):
            clone_text = part.get_text(" ", strip=True)
            label_text = label_node.get_text(" ", strip=True)
            return clone_text[len(label_text) :].strip() or None
    return None


def _star_field(card: Tag, label: str) -> str | None:
    for box in card.select(".star-box"):
        s_label = box.find(class_="s-label")
        if s_label and s_label.get_text(strip=True).lower() == label.lower():
            paragraphs = box.find_all("p")
            return " ".join(_text(p) for p in paragraphs if _text(p)) or None
    return None


def _trade_offs(card: Tag) -> list[str]:
    for part in card.select(".part"):
        label_node = part.find(class_="part-label")
        if label_node and "trade-off" in label_node.get_text(strip=True).lower():
            return [_text(li) for li in part.select("li") if _text(li)]
    return []


def _keywords(card: Tag) -> list[dict]:
    keywords = []
    table = card.find(class_="kw-table")
    if not table:
        return keywords
    rows = table.find_all("tr")[1:]  # skip header row
    for row in rows:
        cells = row.find_all("td")
        if len(cells) == 2:
            term, definition = _text(cells[0]), _text(cells[1])
            if term and definition:
                keywords.append({"term": term, "definition": definition})
    return keywords


def _project_link(card: Tag) -> str | None:
    link_div = card.find(class_="project-link")
    return _text(link_div)


def _leadership(card: Tag) -> str | None:
    for part in card.select(".part.leadership"):
        label_node = part.find(class_="part-label")
        full_text = part.get_text(" ", strip=True)
        label_text = label_node.get_text(" ", strip=True) if label_node else ""
        return full_text[len(label_text) :].strip() or None
    return None


def _parse_cards(soup: BeautifulSoup, fallback_topic: str | None) -> list[dict]:
    cards_out = []
    weeks = soup.select("section.week")
    topic_order = 0
    if weeks:
        for week in weeks:
            topic_order += 1
            w_name = week.find(class_="w-name")
            topic = _text(w_name) or fallback_topic or "Untitled topic"
            card_order = 0
            for card in week.select(".q-card"):
                card_order += 1
                cards_out.append(_card_fields(card, topic, topic_order, card_order))
    else:
        topic = fallback_topic or "Format Prototype"
        card_order = 0
        for card in soup.select(".q-card"):
            card_order += 1
            cards_out.append(_card_fields(card, topic, 0, card_order))
    return cards_out


def _card_fields(card: Tag, topic: str, topic_order: int, card_order: int) -> dict:
    q_text_node = card.find(class_="q-text")
    question = _text(q_text_node) or "Untitled question"
    question = re.sub(r"^Q\d+\.\s*", "", question)  # strip leading "Q7. " numbering - card_order already orders it

    return {
        "topic": topic,
        "topic_order": topic_order,
        "card_order": card_order,
        "question": question,
        "hint": _part_text(card, "Hint"),
        "concept": _part_text(card, "Concept"),
        "situation": _star_field(card, "Situation"),
        "task": _star_field(card, "Task"),
        "action": _star_field(card, "Action"),
        "result": _star_field(card, "Result"),
        "project_link": _project_link(card),
        "leadership_angle": _leadership(card),
        "trade_offs": _trade_offs(card),
        "keywords": _keywords(card),
        "tech_stack": [],
        "feature_references": [],
    }


async def main() -> int:
    store = get_db_gateway().interview_qa_store()
    total = 0

    for file_path, fallback_topic in FILES:
        with open(file_path, encoding="utf-8") as file_handle:
            soup = BeautifulSoup(file_handle.read(), "html.parser")
        cards = _parse_cards(soup, fallback_topic)
        print(f"{file_path}: parsed {len(cards)} card(s)")
        for card in cards:
            row = await store.create_card(card)
            print(f"  inserted id={row['id']}: {row['question'][:70]}")
            total += 1

    print(f"\nTotal cards inserted: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
