use rekamind_recorder::settings::{normalize_server, Settings, UI_ORIGINS};

#[test]
fn only_http_and_https_origins_are_accepted_and_paths_are_dropped() {
    assert_eq!(
        normalize_server("https://rekamind.kantor.id/api?x=1").as_deref(),
        Some("https://rekamind.kantor.id")
    );
    assert_eq!(
        normalize_server("  http://10.0.0.5:8787/ ").as_deref(),
        Some("http://10.0.0.5:8787")
    );
    for bad in [
        "",
        "rekamind.kantor.id",
        "ftp://x",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://",
        "http://user:pw@host",
        "http://a b",
    ] {
        assert_eq!(normalize_server(bad), None, "{bad:?} must be rejected");
    }
}

#[test]
fn remote_mode_needs_a_valid_server_and_local_mode_does_not() {
    let remote = Settings {
        mode: "remote".into(),
        server: "bukan url".into(),
        ..Default::default()
    };
    assert!(remote.validated().unwrap_err().contains("http"));
    let ok = Settings {
        mode: "remote".into(),
        server: "https://x.id/path".into(),
        ..Default::default()
    }
    .validated()
    .unwrap();
    assert_eq!(ok.server_url(), "https://x.id");
    assert_eq!(
        Settings::default().validated().unwrap().server_url(),
        "http://127.0.0.1:8787"
    );
}

#[test]
fn bad_values_are_refused_with_a_message() {
    assert!(Settings {
        mode: "cloud".into(),
        ..Default::default()
    }
    .validated()
    .is_err());
    assert!(Settings {
        local_port: 80,
        ..Default::default()
    }
    .validated()
    .is_err());
    assert!(Settings {
        language: "xx".into(),
        ..Default::default()
    }
    .validated()
    .is_err());
    assert!(Settings {
        local_program: "  ".into(),
        ..Default::default()
    }
    .validated()
    .is_err());
    assert!(Settings {
        hotkey: "".into(),
        ..Default::default()
    }
    .validated()
    .is_err());
}

#[test]
fn the_name_is_trimmed_and_capped() {
    let s = Settings {
        local_user_name: format!("  {}  ", "a".repeat(300)),
        ..Default::default()
    }
    .validated()
    .unwrap();
    assert_eq!(s.local_user_name.len(), 100);
}

#[test]
fn config_and_local_backend_follow_the_mode() {
    let local = Settings::default();
    assert_eq!(
        local.to_config().server.as_deref(),
        Some("http://127.0.0.1:8787")
    );
    assert!(local.local_backend().is_some());
    let remote = Settings {
        mode: "remote".into(),
        server: "https://x.id".into(),
        local_user_name: "Andi".into(),
        ..Default::default()
    };
    assert_eq!(remote.to_config().server.as_deref(), Some("https://x.id"));
    assert_eq!(remote.to_config().local_user_name.as_deref(), Some("Andi"));
    assert!(
        remote.local_backend().is_none(),
        "a remote server is never started or stopped by this app"
    );
}

#[test]
fn the_ui_origins_the_local_backend_must_allow_cover_every_webview() {
    for o in [
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ] {
        assert!(UI_ORIGINS.contains(o));
    }
}

#[test]
fn save_load_round_trips_and_a_corrupt_file_falls_back_to_defaults() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("cfg/settings.json");
    let s = Settings {
        mode: "remote".into(),
        server: "https://x.id".into(),
        local_user_name: "Andi".into(),
        auto_process: false,
        ..Default::default()
    };
    s.save(&p).unwrap();
    assert_eq!(Settings::load(&p), s);
    assert!(
        !p.with_extension("json.tmp").exists(),
        "temp file renamed away"
    );

    std::fs::write(&p, "{ this is not json").unwrap();
    assert_eq!(Settings::load(&p), Settings::default());
    std::fs::write(&p, r#"{"mode":"remote","server":"ftp://nope"}"#).unwrap();
    assert_eq!(
        Settings::load(&p),
        Settings::default(),
        "invalid values never leak in from disk"
    );
    assert_eq!(
        Settings::load(&d.path().join("missing.json")),
        Settings::default()
    );
}

#[test]
fn unknown_and_missing_fields_in_an_old_file_are_tolerated() {
    let d = tempfile::tempdir().unwrap();
    let p = d.path().join("s.json");
    std::fs::write(&p, r#"{"language":"en","some_future_field":1}"#).unwrap();
    let s = Settings::load(&p);
    assert_eq!((s.language.as_str(), s.local_port), ("en", 8787));
}
