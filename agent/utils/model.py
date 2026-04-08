import os

from langchain.chat_models import init_chat_model

OPENAI_RESPONSES_WS_BASE_URL = "wss://api.openai.com/v1"


def make_model(model_id: str, **kwargs: dict):
    model_kwargs = kwargs.copy()

    if model_id.startswith("openai:"):
        model_kwargs["base_url"] = OPENAI_RESPONSES_WS_BASE_URL
        model_kwargs["use_responses_api"] = True
    elif model_id.startswith("bedrock_converse:"):
        region = os.environ.get("AWS_BEDROCK_REGION", "us-east-1")
        profile = os.environ.get("AWS_PROFILE")
        model_kwargs["region_name"] = region
        if profile:
            model_kwargs["credentials_profile_name"] = profile

    return init_chat_model(model=model_id, **model_kwargs)
