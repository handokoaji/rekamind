//! Finding and fetching a newer Rekamind release on GitHub. Nothing here installs anything: it
//! answers "is there a newer version?" and downloads the installer, but only hands it back after
//! its SHA-256 matches the `SHA256SUMS.txt` published on the same release.

use std::cmp::Ordering;
use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::Path;

use serde::Serialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::api::{agent, ApiError};

const REPO: &str = "handokoaji/rekamind";
const SUMS: &str = "SHA256SUMS.txt";
/// Only assets under this prefix are ever downloaded or opened.
const DOWNLOADS: &str = "https://github.com/handokoaji/rekamind/releases/download/";

/// The fixed asset name release.yml gives the Windows installer. Other platforms update by hand.
#[cfg(windows)]
const INSTALLER: Option<&str> = Some("Rekamind-Windows-x64-setup.exe");
#[cfg(not(windows))]
const INSTALLER: Option<&str> = None;

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct Update {
    pub version: String,
    /// The release page, for platforms without a self-installing asset.
    pub html_url: String,
    pub installer_url: Option<String>,
    pub sums_url: Option<String>,
}

fn net(e: ureq::Error) -> ApiError {
    ApiError(format!("tidak bisa memeriksa pembaruan: {e}"))
}

fn io(e: std::io::Error) -> ApiError {
    ApiError(format!("gagal menyimpan pembaruan: {e}"))
}

/// "0.4.0-beta.4" -> ([0, 4, 0], ["beta", "4"]).
fn parse(v: &str) -> Option<([u64; 3], Vec<String>)> {
    let v = v.trim().trim_start_matches('v');
    let (core, pre) = v.split_once('-').unwrap_or((v, ""));
    let mut nums = core.split('.').map(|n| n.parse::<u64>());
    let core = [nums.next()?.ok()?, nums.next()?.ok()?, nums.next()?.ok()?];
    if nums.next().is_some() {
        return None;
    }
    let pre = if pre.is_empty() {
        Vec::new()
    } else {
        pre.split('.').map(String::from).collect()
    };
    Some((core, pre))
}

/// SemVer precedence between two prerelease tags: numbers compare as numbers and sort before words.
fn pre_cmp(a: &[String], b: &[String]) -> Ordering {
    for (x, y) in a.iter().zip(b) {
        let o = match (x.parse::<u64>(), y.parse::<u64>()) {
            (Ok(m), Ok(n)) => m.cmp(&n),
            (Ok(_), Err(_)) => Ordering::Less,
            (Err(_), Ok(_)) => Ordering::Greater,
            (Err(_), Err(_)) => x.cmp(y),
        };
        if o != Ordering::Equal {
            return o;
        }
    }
    a.len().cmp(&b.len())
}

/// Is `candidate` a strictly newer version than `current`? Unparseable input is never "newer".
pub fn is_newer(candidate: &str, current: &str) -> bool {
    let (Some((ca, cp)), Some((ua, up))) = (parse(candidate), parse(current)) else {
        return false;
    };
    if ca != ua {
        return ca > ua;
    }
    match (cp.is_empty(), up.is_empty()) {
        (true, true) => false,
        (true, false) => true, // 1.0.0 is newer than 1.0.0-rc.1
        (false, true) => false,
        (false, false) => pre_cmp(&cp, &up) == Ordering::Greater,
    }
}

/// The newest release that beats `current`. A prerelease is only offered to someone already on one.
pub fn pick(releases: &Value, current: &str) -> Option<Update> {
    let allow_pre = parse(current).is_some_and(|(_, pre)| !pre.is_empty());
    let mut best: Option<(&str, &Value)> = None;
    for r in releases.as_array()? {
        if r["draft"].as_bool().unwrap_or(false) {
            continue;
        }
        if r["prerelease"].as_bool().unwrap_or(false) && !allow_pre {
            continue;
        }
        let Some(tag) = r["tag_name"].as_str() else {
            continue;
        };
        let version = tag.trim_start_matches('v');
        if !is_newer(version, current) {
            continue;
        }
        if let Some((b, _)) = best {
            if !is_newer(version, b) {
                continue;
            }
        }
        best = Some((version, r));
    }
    let (version, r) = best?;
    let asset = |name: &str| {
        r["assets"]
            .as_array()?
            .iter()
            .find(|a| a["name"].as_str() == Some(name))
            .and_then(|a| a["browser_download_url"].as_str())
            .filter(|u| u.starts_with(DOWNLOADS))
            .map(String::from)
    };
    Some(Update {
        version: version.to_string(),
        html_url: format!("https://github.com/{REPO}/releases/tag/v{version}"),
        installer_url: INSTALLER.and_then(asset),
        sums_url: asset(SUMS),
    })
}

/// Ask GitHub whether a release newer than `current` exists.
pub fn check(current: &str) -> Result<Option<Update>, ApiError> {
    let mut resp = agent()
        .get(format!(
            "https://api.github.com/repos/{REPO}/releases?per_page=10"
        ))
        .header("user-agent", "rekamind-desktop")
        .header("accept", "application/vnd.github+json")
        .call()
        .map_err(net)?;
    let status = resp.status().as_u16();
    if status != 200 {
        return Err(ApiError(format!(
            "GitHub menolak permintaan (HTTP {status})"
        )));
    }
    let releases: Value = resp.body_mut().read_json().map_err(net)?;
    Ok(pick(&releases, current))
}

fn get(agent: &ureq::Agent, url: &str) -> Result<ureq::http::Response<ureq::Body>, ApiError> {
    let resp = agent
        .get(url)
        .header("user-agent", "rekamind-desktop")
        .call()
        .map_err(net)?;
    let status = resp.status().as_u16();
    if status != 200 {
        return Err(ApiError(format!("unduhan ditolak (HTTP {status})")));
    }
    Ok(resp)
}

/// The hash `sha256sum` printed for `name` ("<hash>  <name>", a leading `*` marks binary mode).
fn expected_sha256(sums: &str, name: &str) -> Option<String> {
    sums.lines().find_map(|l| {
        let mut p = l.split_whitespace();
        let hash = p.next()?;
        let file = p.next()?.trim_start_matches('*');
        (file == name && hash.len() == 64).then(|| hash.to_ascii_lowercase())
    })
}

/// Download the installer to `dest`. It only appears at `dest` once its SHA-256 matches the one
/// published on the release; otherwise nothing is left behind and the error says why.
pub fn download(u: &Update, dest: &Path) -> Result<(), ApiError> {
    let (Some(url), Some(sums_url), Some(name)) = (&u.installer_url, &u.sums_url, INSTALLER) else {
        return Err(ApiError(
            "rilis ini tidak punya pemasang otomatis untuk komputer ini".into(),
        ));
    };
    let agent = agent();
    let mut sums_resp = get(&agent, sums_url)?;
    let sums = sums_resp.body_mut().read_to_string().map_err(net)?;
    let want = expected_sha256(&sums, name)
        .ok_or_else(|| ApiError(format!("{SUMS} tidak memuat {name}")))?;

    let mut reader = get(&agent, url)?.into_body().into_reader();
    let part = dest.with_extension("part");
    let mut file = File::create(&part).map_err(io)?;
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; 64 * 1024];
    loop {
        let n = reader.read(&mut buf).map_err(io)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
        file.write_all(&buf[..n]).map_err(io)?;
    }
    drop(file);
    let got = format!("{:x}", hasher.finalize());
    if got != want {
        let _ = fs::remove_file(&part);
        return Err(ApiError(
            "berkas unduhan tidak cocok dengan SHA-256 rilis; pembaruan dibatalkan".into(),
        ));
    }
    fs::rename(&part, dest).map_err(io)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn orders_versions_by_semver() {
        assert!(is_newer("0.4.0-beta.5", "0.4.0-beta.4"));
        assert!(is_newer("0.4.0-beta.10", "0.4.0-beta.9")); // numbers, not text
        assert!(is_newer("0.4.0", "0.4.0-rc.1"));
        assert!(is_newer("0.4.1", "0.4.0"));
        assert!(!is_newer("0.4.0-rc.1", "0.4.0"));
        assert!(!is_newer("0.4.0-beta.4", "0.4.0-beta.4"));
        assert!(!is_newer("0.3.9", "0.4.0-beta.4"));
        assert!(!is_newer("not-a-version", "0.4.0"));
    }

    fn release(tag: &str, prerelease: bool) -> Value {
        let url = |n: &str| format!("{DOWNLOADS}{tag}/{n}");
        json!({
            "tag_name": tag, "draft": false, "prerelease": prerelease,
            "assets": [
                { "name": "Rekamind-Windows-x64-setup.exe", "browser_download_url": url("Rekamind-Windows-x64-setup.exe") },
                { "name": "SHA256SUMS.txt", "browser_download_url": url("SHA256SUMS.txt") },
            ],
        })
    }

    #[test]
    fn offers_the_newest_release_and_only_prereleases_to_prerelease_users() {
        let all = json!([
            release("v0.4.0-beta.5", true),
            release("v0.4.0-beta.4", true),
            release("v0.3.0", false)
        ]);
        let u = pick(&all, "0.4.0-beta.4").expect("beta.5 is newer");
        assert_eq!(u.version, "0.4.0-beta.5");
        assert_eq!(
            u.html_url,
            "https://github.com/handokoaji/rekamind/releases/tag/v0.4.0-beta.5"
        );
        assert_eq!(u.installer_url.is_some(), cfg!(windows));
        assert!(u.sums_url.is_some());
        assert!(pick(&all, "0.4.0-beta.5").is_none());
        assert!(
            pick(&all, "0.3.0").is_none(),
            "a stable user is not offered a beta"
        );
        let with_stable = json!([release("v0.4.0-beta.5", true), release("v0.4.0", false)]);
        assert_eq!(pick(&with_stable, "0.3.0").unwrap().version, "0.4.0");
    }

    #[test]
    fn ignores_drafts_and_assets_outside_the_release_downloads() {
        let mut draft = release("v9.9.9", false);
        draft["draft"] = json!(true);
        assert!(pick(&json!([draft]), "0.4.0").is_none());
        let mut foreign = release("v0.5.0", false);
        foreign["assets"][1]["browser_download_url"] = json!("https://evil.example/SHA256SUMS.txt");
        assert!(pick(&json!([foreign]), "0.4.0").unwrap().sums_url.is_none());
    }

    #[test]
    fn reads_the_hash_for_one_file_from_sha256sum_output() {
        let h = "ab".repeat(32);
        let sums = format!(
            "{h}  Rekamind-Linux-x64.deb\n{}  *Rekamind-Windows-x64-setup.exe\n",
            "CD".repeat(32)
        );
        assert_eq!(
            expected_sha256(&sums, "Rekamind-Windows-x64-setup.exe"),
            Some("cd".repeat(32))
        );
        assert_eq!(expected_sha256(&sums, "missing.exe"), None);
        assert_eq!(
            expected_sha256(
                "short  Rekamind-Windows-x64-setup.exe",
                "Rekamind-Windows-x64-setup.exe"
            ),
            None
        );
    }
}
