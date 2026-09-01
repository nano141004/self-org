from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    brain_dir: Path = Path("~/brain")

    llm_primary_model: str = Field(
        "gemini/gemini-2.5-flash",
        validation_alias="PAL_LLM_PRIMARY_MODEL",
    )
    llm_fallback_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "gemini/gemini-2.5-flash-lite",
            "gemini/gemini-2.0-flash",
        ],
        validation_alias="PAL_LLM_FALLBACK_MODELS",
    )
    llm_api_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias=AliasChoices("GEMINI_API_KEYS", "GEMINI_API_KEY"),
    )
    llm_embedding_model: str = Field(
        "gemini/text-embedding-004",
        validation_alias="PAL_LLM_EMBEDDING_MODEL",
    )

    @field_validator("brain_dir", mode="before")
    @classmethod
    def _expand_user(cls, value: object) -> object:
        if isinstance(value, str):
            return Path(value).expanduser()
        if isinstance(value, Path):
            return value.expanduser()
        return value

    @field_validator("llm_fallback_models", mode="before")
    @classmethod
    def _split_comma_list(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("llm_api_keys", mode="before")
    @classmethod
    def _split_api_keys(cls, value: object) -> object:
        if isinstance(value, str):
            keys = [key.strip() for key in value.split(",") if key.strip()]
            if not keys:
                single = os.getenv("GEMINI_API_KEY")
                if single:
                    keys = [single.strip()]
            return keys
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
