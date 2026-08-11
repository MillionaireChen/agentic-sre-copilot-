from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    llm_base_url: str = "http://localhost:8001/v1"
    llm_model: str = "Qwen/Qwen3-8B"
    llm_api_key: str = "dummy"
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dim: int = 1024
    database_url: str = "postgresql+psycopg://sre:sre@localhost:15432/sre"
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"
    demo_service_url: str = "http://localhost:9000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
