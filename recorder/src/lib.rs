//! Rekamind recorder: capture the microphone and the computer's own audio and write them to
//! disk as 16 kHz mono WAV. Nothing else happens while a meeting is running -- no speech
//! recognition, no voice detection, no network -- so it can sit next to a video call and a
//! dozen other apps without being noticed. Transcription happens after the meeting.

pub mod api;
pub mod backend;
pub mod controller;
pub mod engines;
pub mod local_backend;
pub mod login;
pub mod meter;
pub mod resample;
pub mod session;
pub mod settings;
pub mod sink;
pub mod stats;
pub mod timeline;
pub mod uploader;
pub mod wav;

/// Everything downstream (Whisper, pyannote, the browser player) wants this rate.
pub const SAMPLE_RATE: u32 = 16_000;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Source {
    /// The user's microphone.
    Mic,
    /// Everything the computer plays (the other people on a call).
    Speaker,
}

impl Source {
    pub const ALL: [Source; 2] = [Source::Mic, Source::Speaker];

    pub fn file_name(self) -> &'static str {
        match self {
            Source::Mic => "mic.wav",
            Source::Speaker => "speaker.wav",
        }
    }
    /// The name the backend API uses in `/audio/{source}`.
    pub fn api_name(self) -> &'static str {
        match self {
            Source::Mic => "mic",
            Source::Speaker => "speaker",
        }
    }
    /// Plain-language name for messages shown to people.
    pub fn label(self) -> &'static str {
        match self {
            Source::Mic => "Mikrofon",
            Source::Speaker => "Audio komputer",
        }
    }
}
