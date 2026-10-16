#!/usr/bin/env python
"""Phase 181 - mirrors resources/golden_dataset/*.json into Postgres's
golden_dataset_cases table for the Deployment Dashboard's viewer. No S3
involved (unlike sync_admin_docs.py) - this is a plain DB mirror. A re-run
of unchanged cases is a no-op, same dedup principle as sync_admin_docs.py.
Run as: python -m scripts.sync_golden_dataset"""

import asyncio
import json

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway

# dataset key -> local JSON file path
GOLDEN_DATASETS = {
    "genai_rag": "resources/golden_dataset/golden_dataset.json",
    "nfr": "resources/golden_dataset/nfr_golden_dataset.json",
}


async def main() -> int:
    store = get_db_gateway().golden_dataset_store()

    for dataset, local_path in GOLDEN_DATASETS.items():
        with open(local_path, encoding="utf-8") as file_handle:
            data = json.load(file_handle)

        cases = data.get("cases", [])
        if not cases:
            print(f"{dataset}: no cases found in {local_path} - skipping.")
            continue

        for case in cases:
            case_key = case["id"]
            result = await store.upsert_case(
                case_key=case_key,
                dataset=dataset,
                category=case.get("category"),
                query=case.get("query"),
                raw_case=case,
            )
            status = "updated" if result["changed"] else "unchanged"
            print(f"{dataset}/{case_key}: {status} (id={result['id']})")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
