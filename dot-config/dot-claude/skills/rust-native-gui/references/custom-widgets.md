# rust-native-gui — custom widgets (reference)
Read when writing custom, canvas or shader widgets. Parent: `rust-native-gui` SKILL.md.

## Custom, canvas and shader widgets
- **Canvas** (feature `canvas`): implement `canvas::Program<Message>`; cache static layers and clear a `Cache` only when its data changes.
```rust
impl<Message> canvas::Program<Message> for Minimap<'_> {
    type State = ();
    fn draw(&self, _s: &(), renderer: &Renderer, theme: &Theme, bounds: Rectangle, _c: mouse::Cursor)
        -> Vec<canvas::Geometry> {
        let color = theme.palette().text.scale_alpha(0.4);
        vec![self.cache.draw(renderer, bounds.size(), |frame| {
            for (i, len) in self.line_lengths.iter().enumerate() {
                frame.fill_rectangle(Point::new(0.0, i as f32 * 2.0), Size::new(*len as f32, 1.5), color);
            }
        })]
    }
}
// view: canvas(Minimap { line_lengths: &self.line_lengths, cache: &self.minimap }).width(80).height(Fill)
```
  Interaction: `fn update(&self, state, event: &canvas::Event, bounds, cursor) -> Option<canvas::Action<Message>>` returning `canvas::Action::publish(msg)`, `canvas::Action::request_redraw()`, optionally `.and_capture()`; plus `mouse_interaction` for cursors.
- **Custom widget** (feature `advanced`): `impl<Message> advanced::Widget<Message, Theme, Renderer> for Gutter` with `size`, `layout(&mut self, tree, renderer, limits)`, `draw(..)`, optional `tag`/`state` (per-instance state in the widget tree), `children`/`diff`, `operate` (focus/scroll ids), `update(&mut self, tree, event, layout, cursor, renderer, clipboard, shell, viewport)` → `shell.publish(msg)`, `shell.capture_event()`, `shell.request_redraw()`, `shell.invalidate_layout()`; `mouse_interaction`; `overlay`. Provide `impl From<Gutter> for Element<'_, Message>` via `Element::new`. Draw quads with `renderer::Renderer::fill_quad(renderer, renderer::Quad { bounds, .. }, color)`.
- **Shader** widget: `shader::Program` + custom primitives with raw wgpu (0.14 adds a `shader::Pipeline` trait for resource management) for GPU-heavy views (huge plots, image viewers); needs the wgpu renderer.
