# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Public application boundary for speech submission and playback control."""

from aitts.application.ports import SpeechServicePort
from aitts.application.schemas import (
    CancelSpeech,
    CancelSpeechReceipt,
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
    SpeechAdmission,
    SpeechServiceError,
    SpeechStatus,
    SubmissionDisposition,
    VoiceCatalog,
)

__all__ = [
    "CancelSpeech",
    "CancelSpeechReceipt",
    "ClearQueueReceipt",
    "CurrentSpeech",
    "EnqueueSpeech",
    "EnqueueSpeechReceipt",
    "HistoryItem",
    "HistoryQuery",
    "HistoryView",
    "PlaybackControlReceipt",
    "PlaybackState",
    "QueueItem",
    "QueueView",
    "RequeueSpeech",
    "RequeueSpeechReceipt",
    "SpeechAdmission",
    "SpeechServiceError",
    "SpeechServicePort",
    "SpeechStatus",
    "SubmissionDisposition",
    "VoiceCatalog",
]
