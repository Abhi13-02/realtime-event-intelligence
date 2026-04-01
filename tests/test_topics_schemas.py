from pydantic import ValidationError

from app.schemas.topics import (
    DeliveryChannel,
    SensitivityLevel,
    TopicChannelItem,
    TopicChannelsUpdateRequest,
    TopicCreateRequest,
    TopicPatchRequest,
)


def test_topic_create_rejects_blank_name() -> None:
    try:
        TopicCreateRequest(name="   ")
    except ValidationError:
        pass
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("Expected ValidationError for blank name")


def test_topic_create_trims_name_and_description() -> None:
    payload = TopicCreateRequest(
        name="  AI chips  ",
        description="  semiconductors and GPUs  ",
        sensitivity=SensitivityLevel.high,
    )

    assert payload.name == "AI chips"
    assert payload.description == "semiconductors and GPUs"
    assert payload.sensitivity == SensitivityLevel.high


def test_topic_patch_accepts_partial_payload() -> None:
    payload = TopicPatchRequest(is_active=False)

    assert payload.is_active is False
    assert payload.model_fields_set == {"is_active"}


def test_topic_patch_rejects_null_name() -> None:
    try:
        TopicPatchRequest.model_validate({"name": None})
    except ValidationError:
        pass
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("Expected ValidationError for null name")


def test_topic_channels_request_rejects_invalid_channel() -> None:
    try:
        TopicChannelsUpdateRequest.model_validate([{"channel": "pagerduty"}])
    except ValidationError:
        pass
    else:  # pragma: no cover - explicit assertion branch
        raise AssertionError("Expected ValidationError for invalid channel")


def test_topic_channels_request_accepts_valid_channels() -> None:
    payload = TopicChannelsUpdateRequest.model_validate(
        [{"channel": "websocket"}, {"channel": "email"}]
    )

    assert payload.root == [
        TopicChannelItem(channel=DeliveryChannel.websocket),
        TopicChannelItem(channel=DeliveryChannel.email),
    ]
