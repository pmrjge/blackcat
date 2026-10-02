# rust-native-gui — workers (reference)
Read when wiring long-running workers (PTY, LSP, file watcher) into the app. Parent: `rust-native-gui` SKILL.md.

## Long-running workers (PTY, LSP, file watcher)
A worker is a `Subscription::run(fn)` stream that hands the app a command `Sender` first, then streams events:
```rust
use iced::futures::{SinkExt, StreamExt, channel::mpsc};

#[derive(Debug, Clone)]
enum WorkerEvent { Ready(mpsc::Sender<Command>), Line(String), Exited(Option<i32>) }
#[derive(Debug, Clone)]
enum Command { Run(String) }

fn worker() -> impl iced::futures::Stream<Item = WorkerEvent> {
    iced::stream::channel(100, async |mut output: mpsc::Sender<WorkerEvent>| {
        use tokio::io::{AsyncBufReadExt, BufReader};
        let (tx, mut rx) = mpsc::channel::<Command>(32);
        let _ = output.send(WorkerEvent::Ready(tx)).await;       // app stores the Sender in its state
        while let Some(Command::Run(cmd)) = rx.next().await {
            let Ok(mut child) = tokio::process::Command::new("sh").arg("-c").arg(&cmd)
                .stdout(std::process::Stdio::piped()).kill_on_drop(true).spawn() else { continue };
            if let Some(out) = child.stdout.take() {
                let mut lines = BufReader::new(out).lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    let _ = output.send(WorkerEvent::Line(line)).await;
                }
            }
            let code = child.wait().await.ok().and_then(|s| s.code());
            let _ = output.send(WorkerEvent::Exited(code)).await;
        }
    })
}
```
- `Subscription::run` takes a non-capturing fn; when the worker depends on data (project root, server command) use `Subscription::run_with(data, fn)` — `data: Hash` becomes part of the identity, so changing it restarts the worker and keeping it stable keeps the worker alive. `.with(value)` adds context without capturing.
- Blocking readers (e.g. `portable-pty`'s reader is `std::io::Read`) live on a dedicated thread that forwards bytes over a channel. Coalesce output (per ~8–16 ms or per chunk) — one `Message` per byte will swamp `update`.
- When a subscription is no longer returned, iced drops its stream mid-`.await`, so no cleanup code after the loop runs: rely on drop-based cleanup (`kill_on_drop(true)`, RAII guards) and send explicit shutdown commands (e.g. LSP `shutdown`/`exit`) before you stop returning the subscription.
