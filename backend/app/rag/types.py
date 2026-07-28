from typing import Literal

import pydantic

Category = Literal["volume", "frequency", "intensity", "progression"]


class ChunksAndMeta(pydantic.BaseModel):
    chunks: list[str]
    source_id: str
    category: Category


class UpsertResult(pydantic.BaseModel):
    ingested: int
