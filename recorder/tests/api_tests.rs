mod common;
mod mock_server;
use mock_server::{backend_ok, start};
use rekamind_recorder::api::Client;
use rekamind_recorder::Source;

fn write_file(dir: &std::path::Path, name: &str, bytes: &[u8]) -> std::path::PathBuf {
    let p = dir.join(name);
    std::fs::write(&p, bytes).unwrap();
    p
}

#[test]
fn the_full_upload_sequence_reaches_the_backend_in_order_with_the_exact_bytes() {
    let m = start(backend_ok);
    let d = tempfile::tempdir().unwrap();
    let audio: Vec<u8> = (0..300_000u32).map(|i| (i % 251) as u8).collect(); // bigger than one socket read
    let p = write_file(d.path(), "mic.wav", &audio);

    let c = Client::new(&m.url, Some("tok".into()));
    c.health().unwrap();
    let id = c
        .create_meeting("Rapat vendor", "id", Some("Andi"))
        .unwrap();
    assert_eq!(id, "abc123");
    c.upload(&id, Source::Mic, &p).unwrap();
    c.finish(&id).unwrap();
    c.process(&id).unwrap();

    let seen = m.seen.lock().unwrap();
    let seq: Vec<String> = seen
        .iter()
        .map(|r| format!("{} {}", r.method, r.path))
        .collect();
    assert_eq!(
        seq,
        [
            "GET /api/health",
            "POST /api/meetings",
            "PUT /api/meetings/abc123/audio/mic",
            "POST /api/meetings/abc123/finish",
            "POST /api/meetings/abc123/process"
        ]
    );
    let create: serde_json::Value = serde_json::from_slice(&seen[1].body).unwrap();
    assert_eq!(create["title"], "Rapat vendor");
    assert_eq!(create["local_user_name"], "Andi");
    assert_eq!(
        seen[2].body, audio,
        "uploaded bytes must be identical to the file"
    );
    assert_eq!(seen[2].header("content-length"), Some("300000"));
    // health is public and carries no credentials; every call that touches data does
    assert!(seen
        .iter()
        .filter(|r| r.path != "/api/health")
        .all(|r| r.header("authorization") == Some("Bearer tok")));
    assert_eq!(seen[0].header("authorization"), None);
}

#[test]
fn the_servers_own_message_is_shown_not_a_bare_status_code() {
    let m = start(|_| (400, r#"{"detail":"File audio kosong"}"#.into()));
    let d = tempfile::tempdir().unwrap();
    let p = write_file(d.path(), "mic.wav", b"x");
    let e = Client::new(&m.url, None)
        .upload("abc123", Source::Mic, &p)
        .unwrap_err()
        .to_string();
    assert!(e.contains("File audio kosong") && e.contains("400"), "{e}");
}

#[test]
fn an_unreachable_server_says_so_in_plain_words() {
    let e = Client::new("http://127.0.0.1:1", None)
        .health()
        .unwrap_err()
        .to_string();
    assert!(e.contains("tidak bisa menghubungi server"), "{e}");
}

#[test]
fn a_missing_file_is_reported_with_its_path() {
    let m = start(backend_ok);
    let e = Client::new(&m.url, None)
        .upload(
            "abc123",
            Source::Mic,
            std::path::Path::new("/no/such/mic.wav"),
        )
        .unwrap_err()
        .to_string();
    assert!(e.contains("/no/such/mic.wav"), "{e}");
}
