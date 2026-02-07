"""
Prompt testing, model comparison, and calibration routes.
Extracted from main.py.
"""

from typing import Optional

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(tags=["Testing"])


@router.get("/api/admin/prompt-tests/datasets")
async def list_test_datasets(
    domain_id: Optional[str] = None,
    category_id: Optional[str] = None,
):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return {"datasets": await service.list_datasets(domain_id, category_id)}


@router.post("/api/admin/prompt-tests/datasets")
async def create_test_dataset(data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return await service.create_dataset(data)


@router.get("/api/admin/prompt-tests/datasets/{dataset_id}")
async def get_test_dataset(dataset_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    result = await service.get_dataset(dataset_id)
    if not result:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return result


@router.get("/api/admin/prompt-tests/datasets/{dataset_id}/cases")
async def list_test_cases(dataset_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return {"cases": await service.list_test_cases(dataset_id)}


@router.post("/api/admin/prompt-tests/cases")
async def create_test_case(data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return await service.create_test_case(data)


@router.get("/api/admin/prompt-tests/runs")
async def list_test_runs(
    schema_id: Optional[str] = None,
    dataset_id: Optional[str] = None,
):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return {"runs": await service.list_test_runs(schema_id, dataset_id)}


@router.get("/api/admin/prompt-tests/runs/{run_id}")
async def get_test_run(run_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    result = await service.get_test_run(run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Test run not found")
    return result


@router.post("/api/admin/prompt-tests/run")
async def execute_test_run(data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        return await service.run_test_suite(
            data["schema_id"],
            data["dataset_id"],
            provider_name=data.get("provider_name"),
            model_name=data.get("model_name"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================
# Model Comparisons
# =====================


@router.get("/api/admin/prompt-tests/comparisons")
async def list_comparisons(limit: int = 50):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return {"comparisons": await service.list_comparisons(limit)}


@router.get("/api/admin/prompt-tests/comparisons/{comparison_id}")
async def get_comparison(comparison_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    result = await service.get_comparison(comparison_id)
    if not result:
        raise HTTPException(status_code=404, detail="Comparison not found")
    return result


@router.get("/api/admin/prompt-tests/comparisons/{comparison_id}/runs")
async def get_comparison_runs(comparison_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    return await service.get_comparison_runs(comparison_id)


@router.post("/api/admin/prompt-tests/comparisons")
async def create_and_run_comparison(data: dict = Body(...)):
    import asyncio
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    comparison = await service.create_comparison(data)
    # Launch comparison execution in the background
    asyncio.create_task(service.run_comparison(comparison["id"]))
    return comparison


# =====================
# Calibration Mode
# =====================


@router.post("/api/admin/prompt-tests/calibrations")
async def create_and_run_calibration(data: dict = Body(...)):
    import asyncio
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    comparison = await service.create_calibration_comparison(data)
    asyncio.create_task(service.run_calibration(comparison["id"]))
    return comparison


@router.post("/api/admin/prompt-tests/pipeline-calibrations")
async def create_and_run_pipeline_calibration(data: dict = Body(...)):
    import asyncio
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    comparison = await service.create_pipeline_comparison(data)
    asyncio.create_task(service.run_pipeline_calibration(comparison["id"]))
    return comparison


@router.get("/api/admin/prompt-tests/calibrations/{comparison_id}/articles")
async def list_calibration_articles(comparison_id: str):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    articles = await service.list_calibration_articles(comparison_id)
    return {"articles": articles}


@router.post("/api/admin/prompt-tests/calibrations/{comparison_id}/articles/{article_id}/review")
async def review_calibration_article(comparison_id: str, article_id: str, data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        result = await service.review_calibration_article(
            article_id=article_id,
            chosen_config=data.get("chosen_config"),
            golden_extraction=data.get("golden_extraction"),
            notes=data.get("reviewer_notes"),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/admin/prompt-tests/generate-prompt-improvement")
async def generate_prompt_improvement(data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        result = await service.generate_prompt_improvement(data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/admin/prompt-tests/calibrations/{comparison_id}/save-dataset")
async def save_calibration_as_dataset(comparison_id: str, data: dict = Body(...)):
    from backend.services.prompt_testing import get_prompt_testing_service
    service = get_prompt_testing_service()
    try:
        dataset = await service.save_calibration_as_dataset(
            comparison_id=comparison_id,
            name=data["name"],
            description=data.get("description"),
        )
        return dataset
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=400, detail="'name' is required")
