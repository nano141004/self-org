from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    brain_dir: Path = Path("~/brain")

    llm_primary_model: str = Field(
        "gemini/gemini-3.5-flash-lite",
        validation_alias="PAL_LLM_PRIMARY_MODEL",
    )
    llm_fallback_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "gemini/gemini-3.7-flash",
            "gemini/gemini-3.6-flash",
        ],
        validation_alias="PAL_LLM_FALLBACK_MODELS",
    )
    llm_api_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias=AliasChoices("GEMINI_API_KEYS", "GEMINI_API_KEY"),
    )
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias="GEMINI_API_KEY",
        exclude=True,
    )
    llm_embedding_model: str = Field(
        "gemini-embedding-2",
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
            return [key.strip() for key in value.split(",") if key.strip()]
        return value

    @model_validator(mode="after")
    def _fallback_api_key(self) -> Settings:
        if not self.llm_api_keys and self.gemini_api_key:
            self.llm_api_keys = [self.gemini_api_key.strip()]
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
