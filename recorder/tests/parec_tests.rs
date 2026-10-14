#![cfg(unix)]
mod common;
use common::read_wav;
use rekamind_recorder::backend::parec::ParecBackend;
use rekamind_recorder::session::Session;
use rekamind_recorder::sink::SourceState;
use rekamind_recorder::Source;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::Duration;

/// A stand-in for `parec`: any shell snippet that writes raw s16le to stdout.
fn fake_parec(dir: &Path, body: &str) -> String {
    let p = dir.join("parec");
    std::fs::write(&p, format!("#!/bin/sh\n{body}\n")).unwrap();
    std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o755)).unwrap();
    p.to_string_lossy().into_owned()
}
fn wait_ms(ms: u64) {
    std::thread::sleep(Duration::from_millis(ms));
}

#[test]
fn bytes_become_samples_even_when_a_sample_straddles_two_reads() {
    let d = tempfile::tempdir().unwrap();
    // 01 00 | 02 00 | 03 00, but cut as 3 bytes + 3 bytes (a short pause, below the silence-padding threshold).
    let cmd = fake_parec(
        d.path(),
        r"printf '\001\000\002'; sleep 0.05; printf '\000\003\000'; sleep 30",
    );
    let out = d.path().join("rec");
    let s = Session::start(&ParecBackend::with_command(cmd), &out, &[Source::Mic]).unwrap();
    wait_ms(900);
    s.stop();
    let wav = read_wav(&out.join("mic.wav"));
    assert_eq!(
        &wav.samples[..3],
        &[1, 2, 3],
        "no sample lost or mangled at the read boundary"
    );
}

#[test]
fn a_suspended_monitor_that_sends_nothing_is_padded_to_stay_on_the_timeline() {
    let d = tempfile::tempdir().unwrap();
    let cmd = fake_parec(d.path(), "sleep 30"); // never writes: PulseAudio suspended the monitor
    let out = d.path().join("rec");
    let s = Session::start(&ParecBackend::with_command(cmd), &out, &[Source::Speaker]).unwrap();
    wait_ms(1500);
    let st = s.status();
    assert!(
        st.sources[0].seconds > 0.9,
        "timeline advanced to {} s without any data",
        st.sources[0].seconds
    );
    s.stop();
    let wav = read_wav(&out.join("speaker.wav"));
    assert!(wav.samples.len() >= 16000 && wav.samples.iter().all(|v| *v == 0));
}

#[test]
fn parec_dying_mid_recording_is_reported_and_the_audio_so_far_is_kept() {
    let d = tempfile::tempdir().unwrap();
    let cmd = fake_parec(
        d.path(),
        r"head -c 32000 /dev/zero | tr '\000' '\001'; exit 3",
    );
    let out = d.path().join("rec");
    let s = Session::start(&ParecBackend::with_command(cmd), &out, &[Source::Mic]).unwrap();
    wait_ms(800);
    assert!(
        matches!(s.status().sources[0].state, SourceState::Failed(_)),
        "{:?}",
        s.status().sources[0].state
    );
    let fin = s.stop();
    assert!(
        fin.warnings.iter().any(|w| w.contains("parec")),
        "{:?}",
        fin.warnings
    );
    assert!(read_wav(&out.join("mic.wav")).samples.len() >= 16000);
}

#[test]
fn a_missing_parec_tells_the_user_what_to_install() {
    let d = tempfile::tempdir().unwrap();
    let r = Session::start(
        &ParecBackend::with_command("/nonexistent/parec"),
        &d.path().join("rec"),
        &[Source::Mic],
    );
    let msg = r.err().expect("must fail").to_string();
    assert!(msg.contains("pulseaudio-utils"), "{msg}");
}
