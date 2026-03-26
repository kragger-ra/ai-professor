from typing import List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .filter_service import ContentFilter

print("Initializing content filter...")
content_filter = ContentFilter()
print("Warmup...", content_filter.process_text("Привет как дела, лох?"))
print("Warmup done!")

print("Preparing to initialize fastapi APP")
app = FastAPI()
print("Preparing to initialize fastapi APP 2")


class TextRequest(BaseModel):
    text: str


class FilterResponse(BaseModel):
    acceptable: bool
    reason: str
    judge: bool
    topics: List[str]
    score: float
    filtered_text: Optional[str]


@app.post("/filter", response_model=FilterResponse)
async def filter_text(request: TextRequest) -> FilterResponse:
    try:
        result = content_filter.process_text(request.text)
        return FilterResponse(
            acceptable=result.acceptable,
            reason=result.reason,
            judge=result.judge,
            topics=result.topics,
            score=result.score,
            filtered_text=result.filtered_text,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
