use std::env;
use std::path::PathBuf;

fn main() {
    // Get the project root
    let manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let lib_path = PathBuf::from(&manifest_dir).join("lib");
    
    // Tell cargo to look for the prebuilt library
    println!("cargo:rustc-link-search=native={}", lib_path.display());
    println!("cargo:rustc-link-lib=dylib=livekit_ffi");
    
    // Tell cargo to rerun if the library changes
    println!("cargo:rerun-if-changed=lib/liblivekit_ffi.so");
    
    // Set the environment variable for runtime
    println!("cargo:rustc-env=LD_LIBRARY_PATH={}:$LD_LIBRARY_PATH", lib_path.display());
}
