import Mathlib

theorem pf_0047 : ∀ x y : ℤ, 3 * x ^ 2 - 5 * y ^ 2 ≠ 4 := by
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 5)) h
  push_cast at h'
  generalize (x : ZMod 5) = u at h'
  generalize (y : ZMod 5) = v at h'
  revert u v
  decide
