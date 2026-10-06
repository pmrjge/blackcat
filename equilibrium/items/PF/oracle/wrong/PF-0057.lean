import Mathlib

theorem pf_0057 : ∀ x y : ℤ, 5 * x ^ 2 + 7 * y ^ 2 ≠ 15 := by
  have eq_gap : ∀ u v : ZMod 4, 5 * u ^ 2 + 7 * v ^ 2 ≠ 15 := by
    decide
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 7)) h
  push_cast at h'
  generalize (x : ZMod 7) = u at h'
  generalize (y : ZMod 7) = v at h'
  revert u v
  decide
