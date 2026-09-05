# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Public application boundaries for speech control and cache policy."""

from aitts.application.cache import (
    DEFAULT_CACHE_MAX_BYTES,
    AudioCachePort,
    CacheController,
    CacheEnforcementReport,
    CacheEntry,
    CacheMetadataPort,
)
from aitts.application.lifecycle import ProcessTerminationPort
from aitts.application.ports import SpeechServicePort
from aitts.application.schemas import (
    CancelSpeech,
    CancelSpeechReceipt,
    CaptionSettings,
    ClearQueueReceipt,
    CurrentSpeech,
    EnqueueSpeech,
    EnqueueSpeechReceipt,
    HistoryItem,
    HistoryQuery,
    HistoryView,
    PlaybackControlReceipt,
    PlaybackState,
    QueueItem,
    QueueView,
    RequeueSpeech,
    RequeueSpeechReceipt,
    SetCaptionsEnabled,
    SpeechAdmission,
    SpeechServiceError,
    SpeechStatus,
    SubmissionDisposition,
    VoiceCatalog,
)
from aitts.model import ContentFormat

__all__ = [
    "DEFAULT_CACHE_MAX_BYTES",
    "AudioCachePort",
    "CacheController",
    "CacheEnforcementReport",
    "CacheEntry",
    "CacheMetadataPort",
    "CancelSpeech",
    "CancelSpeechReceipt",
    "CaptionSettings",
    "ClearQueueReceipt",
    "ContentFormat",
    "CurrentSpeech",
    "EnqueueSpeech",
    "EnqueueSpeechReceipt",
    "HistoryItem",
    "HistoryQuery",
    "HistoryView",
    "PlaybackControlReceipt",
    "PlaybackState",
    "ProcessTerminationPort",
    "QueueItem",
    "QueueView",
    "RequeueSpeech",
    "RequeueSpeechReceipt",
    "SetCaptionsEnabled",
    "SpeechAdmission",
    "SpeechServiceError",
    "SpeechServicePort",
    "SpeechStatus",
    "SubmissionDisposition",
    "VoiceCatalog",
]
