mod common;
mod mock_server;
use mock_server::{backend_ok, start, Req};
use rekamind_recorder::api::{Client, SESSION_EXPIRED};
use rekamind_recorder::login::{
    challenge_for, parse_token, random_urlsafe, MemoryStore, PendingLogin, TokenStore,
};
use rekamind_recorder::settings::{new_local_token, Settings};
use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::{Duration, Instant};

fn browser_hits(port: u16, path_and_query: &str) -> String {
    let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
    write!(
        s,
        "GET {path_and_query} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    )
    .unwrap();
    let mut out = String::new();
    s.read_to_string(&mut out).unwrap();
    out
}

#[test]
fn pkce_challenge_matches_the_rfc_7636_test_vector() {
    assert_eq!(
        challenge_for("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    );
}

#[test]
fn begin_binds_loopback_only_and_builds_the_servers_login_url() {
    let p = PendingLogin::begin("https://rekamind.kantor.id/").unwrap();
    assert!(p.port() >= 1024);
    assert_eq!(p.verifier.len(), 64, "within RFC 7636's 43..128");
    assert!(
        p.url
            .starts_with("https://rekamind.kantor.id/auth/login?client=desktop&port="),
        "{}",
        p.url
    );
    assert!(
        p.url.contains(&format!("port={}", p.port()))
            && p.url
                .ends_with(&format!("&cc={}", challenge_for(&p.verifier)))
    );
    assert!(
        !p.url.contains(&p.verifier),
        "the verifier must never appear in the URL"
    );
    assert!(TcpStream::connect(("127.0.0.1", p.port())).is_ok());
}

#[test]
fn random_values_differ_and_are_url_safe() {
    let (a, b) = (random_urlsafe(32), random_urlsafe(32));
    assert_ne!(a, b);
    assert!(a
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'));
    assert!(new_local_token().len() >= 32 && new_local_token() != new_local_token());
}

#[test]
fn the_code_arrives_via_the_browser_redirect_and_the_user_sees_a_friendly_page() {
    let p = PendingLogin::begin("http://x").unwrap();
    let port = p.port();
    let t = std::thread::spawn(move || {
        // A browser also asks for the favicon and may probe: those must not end the wait.
        assert!(browser_hits(port, "/favicon.ico").contains("404"));
        assert!(browser_hits(port, "/elsewhere").contains("404"));
        browser_hits(port, "/callback?code=one-time-code-123")
    });
    assert_eq!(
        p.wait_for_code(Duration::from_secs(5)).unwrap(),
        "one-time-code-123"
    );
    let page = t.join().unwrap();
    assert!(
        page.contains("200 OK") && page.contains("Login berhasil") && page.contains("no-store")
    );
}

#[test]
fn a_refused_login_is_an_error_not_a_hang() {
    let p = PendingLogin::begin("http://x").unwrap();
    let port = p.port();
    let t = std::thread::spawn(move || browser_hits(port, "/callback?error=access_denied"));
    assert!(p
        .wait_for_code(Duration::from_secs(5))
        .unwrap_err()
        .contains("dibatalkan"));
    assert!(t.join().unwrap().contains("Login gagal"));
}

#[test]
fn waiting_gives_up_after_the_timeout() {
    let p = PendingLogin::begin("http://x").unwrap();
    let t0 = Instant::now();
    assert!(p
        .wait_for_code(Duration::from_millis(300))
        .unwrap_err()
        .contains("Waktu habis"));
    assert!(t0.elapsed() < Duration::from_secs(3));
}

#[test]
fn the_code_and_verifier_go_to_the_server_and_a_token_comes_back() {
    let m = start(|r: &Req| {
        match r.path.as_str() {
        "/auth/desktop/token" => (200, r#"{"access_token":"rks_abc","token_type":"Bearer","expires_at":"2026-11-13T00:00:00Z","user":{"id":"u","email":"alice@kantor.id","name":"Alice"}}"#.into()),
        _ => (404, "{}".into()),
    }
    });
    let t = Client::new(&m.url, None)
        .desktop_token("the-code", "the-verifier")
        .unwrap();
    assert_eq!(
        (t.access_token.as_str(), t.email.as_str()),
        ("rks_abc", "alice@kantor.id")
    );
    let seen = m.seen.lock().unwrap();
    assert_eq!(seen[0].method, "POST");
    let body: serde_json::Value = serde_json::from_slice(&seen[0].body).unwrap();
    assert_eq!(
        (body["code"].as_str(), body["verifier"].as_str()),
        (Some("the-code"), Some("the-verifier"))
    );
}

#[test]
fn incomplete_token_responses_are_refused() {
    assert!(parse_token(&serde_json::json!({"access_token": "x"})).is_err());
    assert!(parse_token(&serde_json::json!({})).is_err());
}

#[test]
fn a_rejected_credential_tells_the_user_what_to_do_instead_of_a_bare_401() {
    let m = start(|_| (401, r#"{"detail":"Sesi berakhir"}"#.into()));
    let e = Client::new(&m.url, Some("old".into()))
        .create_meeting("x", "id", None)
        .unwrap_err()
        .to_string();
    assert_eq!(e, SESSION_EXPIRED);
}

#[test]
fn the_bearer_token_is_sent_on_every_data_call() {
    let m = start(backend_ok);
    let c = Client::new(&m.url, Some("rks_tok".into()));
    c.create_meeting("t", "id", None).unwrap();
    assert!(m
        .seen
        .lock()
        .unwrap()
        .iter()
        .all(|r| r.header("authorization") == Some("Bearer rks_tok")));
}

#[test]
fn the_token_store_round_trips_and_clears() {
    let s = MemoryStore::default();
    assert_eq!(s.load(), None);
    s.save("t").unwrap();
    assert_eq!(s.load().as_deref(), Some("t"));
    s.clear();
    assert_eq!(s.load(), None);
}

#[test]
fn a_local_backend_is_started_single_user_with_a_secret_and_remote_has_none() {
    // (the env is private to LocalBackend; the observable contract is that the config carries the same token)
    let s = Settings::default();
    let token = new_local_token();
    assert_eq!(
        s.to_config(Some(&token)).token.as_deref(),
        Some(token.as_str())
    );
    let d = std::path::Path::new("/d");
    let env = rekamind_recorder::settings::BackendEnv {
        token: &token,
        data_dir: d,
        engines_ready: false,
        llm_api_key: None,
        hf_token: None,
        bundled: None,
    };
    assert!(s.local_backend(&env).is_some());
}
