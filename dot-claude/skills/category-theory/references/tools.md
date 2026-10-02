# Category theory in practice: tools

Read when using a proof assistant, library or diagram tool for category theory (moved from `category-theory` SKILL.md).

## 10. Tools
- Lean/Mathlib: the `lean-formalization` skill §8 lists notation (`⟶`, `≫`, `⥤`, `⋙`, `≅`, `⊣`, `⊗`),
  names and files.
- Commutative diagrams:
  - tikz-cd (`\usepackage{amssymb,tikz-cd}`).
  - quiver (https://q.uiver.app): draw, then export tikz-cd with an embedded link back to the diagram.
    Its curved and shortened arrow styles need `\usepackage{quiver}`; `quiver.sty` wraps tikz-cd and
    ships in the quiver repository.
- tikz-cd cheat sheet (compiled with pdflatex):
```latex
\begin{tikzcd}                                   % pullback square
P \arrow[r] \arrow[d] \arrow[dr, phantom, "\lrcorner", very near start] & X \arrow[d, "f"] \\
Y \arrow[r, "g"'] & Z                            % "g"' puts the label on the other side
\end{tikzcd}
\begin{tikzcd}                                   % mono, epi, unique dashed map, parallel pair
A \arrow[r, hook] & B \arrow[r, two heads] & C \arrow[r, dashed, "\exists!"]
  & D \arrow[r, shift left, "f"] \arrow[r, shift right, "g"'] & E
\end{tikzcd}
\begin{tikzcd}                                   % adjunction F -| G
\mathcal C \arrow[r, bend left=30, "F", ""{name=U, below}]
  & \mathcal D \arrow[l, bend left=30, "G", ""{name=L, above}]
\arrow[phantom, from=U, to=L, "\dashv" rotate=-90]
\end{tikzcd}
\begin{tikzcd}                                   % 2-cell alpha: F => G
\mathcal C \arrow[r, bend left=50, "F", ""{name=F, below}]
  \arrow[r, bend right=50, "G"', ""{name=G, above}] & \mathcal D
\arrow[Rightarrow, from=F, to=G, "\alpha"]
\end{tikzcd}
```
  More options:
  - `"f" description` (label on the arrow), `dotted`, `crossing over`, `bend right`, `Rightarrow`.
  - Inside macros or Beamer frames: `ampersand replacement=\&`.
  - Pushout corner, from the pushout vertex Q: `\arrow[ul, phantom, "\ulcorner", very near start]`.
- Finite experiments: encode a finite category as hom-sets plus a composition table (plain Python or
  networkx) and brute-force associativity, functoriality and naturality.
