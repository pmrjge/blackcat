---
name: ts-types-validation
description: Use for TS type design and runtime validation — zod 4, unions, brands, generics.
---
# TypeScript types and runtime validation

Part of `typescript-engineering` (baseline versions, async rules). zod 4.6.5 is `latest` (Verified 2026-10-02 https://registry.npmjs.org/zod/latest).

## Runtime validation (zod 4)
- Validate at every boundary — HTTP bodies, env, files, `postMessage`, LLM/tool output — then pass typed values inward.
```ts
import { z } from "zod";                        // zod@4: the root export is the v4 API; "zod/mini" for small bundles
const Config = z.object({
  port: z.number().int().min(1).max(65535).default(8080),
  host: z.string().default("127.0.0.1"),
  tags: z.array(z.string()).optional(),
});
export type Config = z.infer<typeof Config>;
export function parseConfig(input: unknown): Config {
  const r = Config.safeParse(input);
  if (!r.success) throw new Error(z.prettifyError(r.error));
  return r.data;
}
```
- Parse `process.env` once at startup into a typed config and fail fast. Zod 4 has top-level string formats (`z.email()`, `z.url()`) and prefers the `error` option over `message`.

## Type patterns
```ts
type Shape = { kind: "circle"; r: number } | { kind: "rect"; w: number; h: number };
function area(s: Shape): number {
  switch (s.kind) {
    case "circle": return Math.PI * s.r ** 2;
    case "rect": return s.w * s.h;
    default: { const unreachable: never = s; throw new Error(`unhandled ${JSON.stringify(unreachable)}`); }
  }
}
declare const brand: unique symbol;
type Brand<T, B extends string> = T & { readonly [brand]: B };
type UserId = Brand<string, "UserId">;          // IDs and units can't be mixed up
const palette = { primary: "#0af" } satisfies Record<string, `#${string}`>; // checked, keeps literal types
```
- `unknown` instead of `any`; narrow with guards or schemas; `// @ts-expect-error <reason>` rather than `@ts-ignore`.
- Generics only when a type parameter links two positions (input ↔ output); constrain them; `NoInfer<T>` stops inference from a parameter; prefer unions or overloads for two or three cases.
- Replace enums with `as const` objects + union types (erasable). `readonly` arrays/tuples in parameters.
- Expected failures as result unions (`{ ok: true; value } | { ok: false; error }`); exceptions for bugs.

## Verify
- [ ] `tsc --noEmit` clean under the strict config; no new `any`, `as` casts justified, `@ts-expect-error` has a reason.
- [ ] Boundaries validated with schemas; env parsed once; errors carry `cause`.
- [ ] Type-level behaviour pinned with `expectTypeOf` tests where a type is the API (`ts-testing`).
