mod common;
mod mock_server;
use common::read_wav;
use mock_server::{backend_ok, start};
use std::process::Command;

fn rec() -> Command {
    Command::new(env!("CARGO_BIN_EXE_rekamind-rec"))
}

#[test]
fn records_synthetic_audio_to_equal_length_valid_files() {
    let d = tempfile::tempdir().unwrap();
    let out = rec()
        .args([
            "record",
            "--synthetic",
            "--duration",
            "2",
            "--stats",
            "--out",
        ])
        .arg(d.path())
        .output()
        .unwrap();
    let err = String::from_utf8_lossy(&out.stderr);
    assert!(out.status.success(), "{err}");
    assert!(
        err.contains("[stats] CPU:") && err.contains("memori puncak"),
        "self-measurement missing: {err}"
    );
    let folder = std::fs::read_dir(d.path())
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let (mic, spk) = (
        read_wav(&folder.join("mic.wav")),
        read_wav(&folder.join("speaker.wav")),
    );
    assert_eq!(mic.samples.len(), spk.samples.len());
    assert!(
        mic.samples.len() >= 16000 * 3 / 2,
        "about two seconds, got {}",
        mic.samples.len()
    );
}

#[test]
fn record_then_upload_and_process_in_one_command() {
    let m = start(backend_ok);
    let d = tempfile::tempdir().unwrap();
    let out = rec()
        .args([
            "record",
            "--synthetic",
            "--duration",
            "1",
            "--process",
            "--title",
            "Uji CLI",
            "--name",
            "Andi",
            "--server",
            &m.url,
            "--out",
        ])
        .arg(d.path())
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let seen = m.seen.lock().unwrap();
    let seq: Vec<String> = seen
        .iter()
        .map(|r| format!("{} {}", r.method, r.path))
        .collect();
    assert!(
        seq.contains(&"PUT /api/meetings/abc123/audio/mic".to_string())
            && seq.contains(&"PUT /api/meetings/abc123/audio/speaker".to_string()),
        "{seq:?}"
    );
    assert_eq!(seq.last().unwrap(), "POST /api/meetings/abc123/process");
    let create = seen
        .iter()
        .find(|r| r.path == "/api/meetings" && r.method == "POST")
        .unwrap();
    let body: serde_json::Value = serde_json::from_slice(&create.body).unwrap();
    assert_eq!(
        (body["title"].as_str(), body["local_user_name"].as_str()),
        (Some("Uji CLI"), Some("Andi"))
    );
}

#[test]
fn if_the_server_is_down_the_recording_is_kept_and_the_user_is_told_how_to_retry() {
    let d = tempfile::tempdir().unwrap();
    let out = rec()
        .args([
            "record",
            "--synthetic",
            "--duration",
            "1",
            "--server",
            "http://127.0.0.1:1",
            "--out",
        ])
        .arg(d.path())
        .output()
        .unwrap();
    let err = String::from_utf8_lossy(&out.stderr);
    assert_eq!(out.status.code(), Some(2), "{err}");
    assert!(
        err.contains("AMAN di disk") && err.contains("rekamind-rec upload"),
        "{err}"
    );
    let folder = std::fs::read_dir(d.path())
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    assert_eq!(
        read_wav(&folder.join("mic.wav")).rate,
        16000,
        "audio is intact"
    );
}

#[test]
fn a_kept_recording_can_be_uploaded_later() {
    let d = tempfile::tempdir().unwrap();
    rec()
        .args(["record", "--synthetic", "--duration", "1", "--out"])
        .arg(d.path())
        .output()
        .unwrap();
    let folder = std::fs::read_dir(d.path())
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let m = start(backend_ok);
    let out = rec()
        .args(["upload"])
        .arg(&folder)
        .args(["--server", &m.url, "--title", "Susulan"])
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(m
        .seen
        .lock()
        .unwrap()
        .iter()
        .any(|r| r.path.ends_with("/audio/speaker")));
}

#[test]
fn recover_repairs_a_crashed_recording_from_the_command_line() {
    let d = tempfile::tempdir().unwrap();
    rec()
        .args(["record", "--synthetic", "--duration", "1", "--out"])
        .arg(d.path())
        .output()
        .unwrap();
    let folder = std::fs::read_dir(d.path())
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    // Corrupt the header the way a crash would: claim zero data.
    let p = folder.join("mic.wav");
    let mut b = std::fs::read(&p).unwrap();
    b[40..44].copy_from_slice(&0u32.to_le_bytes());
    b[4..8].copy_from_slice(&36u32.to_le_bytes());
    std::fs::write(&p, b).unwrap();
    let out = rec().arg("recover").arg(&folder).output().unwrap();
    assert!(out.status.success() && String::from_utf8_lossy(&out.stderr).contains("diperbaiki"));
    assert!(read_wav(&p).samples.len() >= 16000);
}

#[test]
fn bad_arguments_print_help_instead_of_crashing() {
    let out = rec().args(["record", "--bogus"]).output().unwrap();
    assert_eq!(out.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&out.stderr).contains("PEMAKAIAN"));
}

#[test]
fn nothing_to_record_is_a_clear_failure() {
    let d = tempfile::tempdir().unwrap();
    let out = rec()
        .args([
            "record",
            "--no-mic",
            "--no-speaker",
            "--synthetic",
            "--duration",
            "1",
            "--out",
        ])
        .arg(d.path())
        .output()
        .unwrap();
    assert_eq!(out.status.code(), Some(1));
}
