import Mathlib

theorem pf_0050 : ∀ x y : ℤ, x ^ 3 + y ^ 3 ≠ 3 := by
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 7)) h
  push_cast at h'
  generalize (x : ZMod 7) = u at h'
  generalize (y : ZMod 7) = v at h'
  revert u v
  decide
