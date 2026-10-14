use std::sync::Arc;

use crate::sink::SourceCtx;
use crate::Source;

#[cfg(unix)]
pub mod parec;
pub mod synthetic;
#[cfg(windows)]
pub mod wasapi_backend;

/// A running capture; dropping or stopping it ends the capture thread.
pub trait Capture: Send {
    fn stop(self: Box<Self>);
}

pub trait Backend {
    /// Begin feeding `ctx`. An Err means this source cannot be used at all right now.
    fn start(&self, ctx: Arc<SourceCtx>) -> Result<Box<dyn Capture>, String>;
}

/// The right backend for this operating system.
pub fn default_backend() -> Box<dyn Backend> {
    #[cfg(windows)]
    {
        Box::new(wasapi_backend::WasapiBackend::new())
    }
    #[cfg(unix)]
    {
        Box::new(parec::ParecBackend::new())
    }
}

#[allow(dead_code)]
fn _assert_source_is_used(_: Source) {}
