# Editor engineering: files search

Read when implementing file loading, watching or search (moved from `editor-engineering` SKILL.md).

## Files, watching and search
- Watching: `notify::recommended_watcher` (FSEvents on macOS, inotify on Linux) + `notify-debouncer-full` (coalesces bursts, tracks renames). Editors save via rename or truncate, so treat every event as "maybe changed" and compare mtime/size/hash before reloading. Skip ignored dirs (`target/`, `node_modules/`, `.git/objects`); Linux inotify limits (`fs.inotify.max_user_watches`); `PollWatcher` for network filesystems.
- External change: clean buffer → reload and keep cursors by diff-mapping (`imara-diff`, `similar`); dirty buffer → conflict prompt.
- Project search (ripgrep's crates):
```rust
let matcher = RegexMatcher::new_line_matcher(r"fn\s+main")?;
WalkBuilder::new(root).build_parallel().run(|| {             // honors .gitignore/.ignore, hidden files
    let (tx, matcher, cancelled) = (tx.clone(), matcher.clone(), cancelled.clone()); // cancelled: Arc<AtomicBool>
    let mut searcher = SearcherBuilder::new()
        .binary_detection(BinaryDetection::quit(b'\x00')).line_number(true).build();
    Box::new(move |entry| {
        let Ok(entry) = entry else { return WalkState::Continue };
        if !entry.file_type().is_some_and(|t| t.is_file()) { return WalkState::Continue; }
        let path = entry.path().to_path_buf();
        let _ = searcher.search_path(&matcher, &path, UTF8(|lnum, line| {
            let _ = tx.send((path.clone(), lnum, line.to_string()));
            Ok(true)
        }));
        if cancelled.load(Ordering::Relaxed) { WalkState::Quit } else { WalkState::Continue }
    })
});
```
  Stream hits to the UI in batches; cancel on a new query via the shared flag; cap results.
