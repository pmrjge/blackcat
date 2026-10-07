# Perm-view shift: old i*ceil(S/N) mod S vs new floor(i*S/N), N=5 (and 3). Two routes: arithmetic and explicit rotations.
import math
def sh_old(i,S,N): return (i*math.ceil(S/N)) % S
def sh_new(i,S,N): return (i*S)//N
def latin_rect(shifts,S):  # route 2: build rotations, check each position holds distinct segments across members
    rows=[[(p+s)%S for p in range(S)] for s in shifts]
    return all(len({r[p] for r in rows})==len(rows) for p in range(S))
for N in (5,3):
    print(f"N={N}: S, old shifts (distinct), new shifts (distinct), new max gap-min gap")
    bad_old=[]; bad_new=[]
    for S in range(2,41):
        o=[sh_old(i,S,N) for i in range(N)]; n=[sh_new(i,S,N) for i in range(N)]
        do,dn=len(set(o)),len(set(n)); need=min(N,S)
        assert (do==N)==latin_rect(o,S) and (dn==N)==latin_rect(n,S)
        if do<need: bad_old.append(S)
        if dn<need: bad_new.append(S)
        assert all(0<=x<S for x in n) and n==sorted(n)
        gaps=[(n[(k+1)%N]-n[k])%S if N<=S else None for k in range(N)]
        if S<=20: print(f"  S={S}: old {o} ({do}) new {n} ({dn}) gaps {gaps}")
    print(f"  S in 2..40 with fewer than min(N,S) distinct shifts: old {bad_old}; new {bad_new}")
