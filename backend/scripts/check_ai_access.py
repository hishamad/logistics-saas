"""Print safe provider diagnostics only; never print credentials or raw error bodies."""

import json

from openai import APIError, OpenAI

from freight.ai import InterpretationError, propose_rule
from freight.fixtures import demo_snapshot
from freight.settings import get_settings


def main() -> None:
    settings = get_settings()
    try:
        result = propose_rule(demo_snapshot(), "Assign SFD-1041 to Team 02. This is required.")
        print(json.dumps({"status": result["status"], "model": result.get("model")}))
    except InterpretationError as exc:
        cause = exc.__cause__
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "exception": type(cause).__name__,
                    "status": getattr(cause, "status_code", None),
                    "code": getattr(cause, "code", None),
                    "param": getattr(cause, "param", None),
                }
            )
        )
        if settings.openai_api_key:
            try:
                with OpenAI(
                    api_key=settings.openai_api_key.get_secret_value(), timeout=15, max_retries=0
                ) as client:
                    models = client.models.list()
                    print(
                        json.dumps(
                            {
                                "available_text_models": sorted(
                                    m.id
                                    for m in models
                                    if m.id.startswith("gpt-")
                                    and not any(
                                        x in m.id
                                        for x in ("audio", "realtime", "image", "transcribe", "tts")
                                    )
                                )
                            }
                        )
                    )
            except APIError as error:
                print(
                    json.dumps(
                        {
                            "model_list_status": getattr(error, "status_code", None),
                            "code": getattr(error, "code", None),
                        }
                    )
                )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
