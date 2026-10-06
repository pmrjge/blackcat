# Probability that the CP-upper<0.6 refutation fires when pi=0.5 (null) or pi=0.6, at fixed n_d.
from scipy import stats
def cpu(k,n): return 1.0 if k==n else stats.beta.ppf(0.975,k+1,n-k)
for n in (29,35,42,46,50):
    kmax=max(k for k in range(n+1) if cpu(k,n)<0.6)
    print(n, "k<=",kmax, "P(refute|pi=.5)=%.3f"%stats.binom.cdf(kmax,n,.5), "P(refute|pi=.6)=%.3f"%stats.binom.cdf(kmax,n,.6))
print("-- excluding the powered effect: CP two-sided 95% upper < 0.75 --")
for n in (29,35,42,46,50):
    kmax=max(k for k in range(n+1) if cpu(k,n)<0.75)
    print(n, "k<=",kmax, "P(excl|pi=.5)=%.3f"%stats.binom.cdf(kmax,n,.5), "P(excl|pi=.6)=%.3f"%stats.binom.cdf(kmax,n,.6), "P(excl|pi=.75)=%.3f"%stats.binom.cdf(kmax,n,.75))
