from app.schemas.topics import DeliveryChannel, TopicChannelItem
from app.services.topics import _normalized_name_key, _unique_channels


def test_normalized_name_key_is_trimmed_and_case_insensitive() -> None:
    assert _normalized_name_key("  AI Chips  ") == "ai chips"


def test_unique_channels_preserves_first_seen_order() -> None:
    channels = [
        TopicChannelItem(channel=DeliveryChannel.websocket),
        TopicChannelItem(channel=DeliveryChannel.email),
        TopicChannelItem(channel=DeliveryChannel.websocket),
    ]

    assert _unique_channels(channels) == [
        DeliveryChannel.websocket,
        DeliveryChannel.email,
    ]
