/*
 * Adaptive Markov Page Prefetcher with Pressure-Aware Eviction -- C core.
 *
 * A standalone reimplementation of the simulator's hot path: the deterministic
 * workload generators, the LRU and CLOCK baselines, and the full adaptive
 * pipeline (order-2 Markov predictor, phase detector, policy engine, and a
 * frame set supporting FIFO / LRU / MRU eviction with pressure-aware prefetch
 * gating). It mirrors the Python reference in python/ampp and is expected to
 * produce the same hit rates and fault-reduction figures.
 *
 * The strongest classical baseline, ARC, lives in the Python reference; this
 * core targets the throughput path (LRU is the baseline the resume line is
 * measured against, and AMPP is the contribution).
 *
 * Build:  make          (or: cc -O2 -o ampp ampp.c)
 * Run:    ./ampp
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* Page ids across all workloads stay well under this bound, so page-indexed
 * arrays give O(1) resident-set maps without a hash table. */
#define MAXP 8192

/* ------------------------------------------------------------------ *
 * Deterministic RNG (LCG) so the random workload is reproducible.
 * ------------------------------------------------------------------ */
static uint64_t rng_state;
static void rng_seed(uint64_t s) { rng_state = s ? s : 1; }
static uint32_t rng_next(void) {
    rng_state = rng_state * 6364136223846793005ULL + 1442695040888963407ULL;
    return (uint32_t)(rng_state >> 33);
}
static int rng_below(int n) { return (int)(rng_next() % (uint32_t)n); }

/* ------------------------------------------------------------------ *
 * Workload generators. Scan and loop traces are identical to the Python
 * reference; the random trace matches it statistically, not bit-for-bit.
 * ------------------------------------------------------------------ */
typedef enum { W_SEQUENTIAL, W_RANDOM, W_LOOPING, W_MIXED } Workload;

static int *gen_trace(Workload w, int length, unsigned seed) {
    int *t = malloc(sizeof(int) * (size_t)length);
    rng_seed(seed);
    if (w == W_SEQUENTIAL) {
        for (int i = 0; i < length; i++) t[i] = i % 500;
    } else if (w == W_RANDOM) {
        for (int i = 0; i < length; i++) t[i] = rng_below(300);
    } else if (w == W_LOOPING) {
        for (int i = 0; i < length; i++) t[i] = i % 120;
    } else { /* mixed: scan, loop, random, scan, loop (random = 20%) */
        const char *sched[5] = {"scan", "loop", "rand", "scan", "loop"};
        int seg = 1000, step = 0, pos = 0;
        while (pos < length) {
            int n = (length - pos < seg) ? (length - pos) : seg;
            const char *kind = sched[step % 5];
            for (int i = 0; i < n; i++) {
                if (kind[0] == 's') t[pos + i] = 0 + (i % 500);
                else if (kind[0] == 'l') t[pos + i] = 1000 + (i % 120);
                else t[pos + i] = 2000 + rng_below(300);
            }
            pos += n; step++;
        }
    }
    return t;
}

/* ------------------------------------------------------------------ *
 * Shared statistics.
 * ------------------------------------------------------------------ */
typedef struct {
    long accesses, hits, faults, prefetches, prefetch_hits;
} Stats;

static double hit_rate(const Stats *s) {
    return s->accesses ? (double)s->hits / (double)s->accesses : 0.0;
}

/* ------------------------------------------------------------------ *
 * LRU baseline (doubly linked recency list, page-indexed).
 * ------------------------------------------------------------------ */
typedef struct {
    int cap, size;
    char resident[MAXP];
    int rprev[MAXP], rnext[MAXP];  /* recency list; head = LRU, tail = MRU */
    int head, tail;
    Stats st;
} LRU;

static void list_unlink(int *rprev, int *rnext, int *head, int *tail, int p) {
    if (rprev[p] == -1) *head = rnext[p]; else rnext[rprev[p]] = rnext[p];
    if (rnext[p] == -1) *tail = rprev[p]; else rprev[rnext[p]] = rprev[p];
    rprev[p] = rnext[p] = -1;
}
static void list_push_tail(int *rprev, int *rnext, int *head, int *tail, int p) {
    rprev[p] = *tail; rnext[p] = -1;
    if (*tail == -1) *head = p; else rnext[*tail] = p;
    *tail = p;
}

static void lru_init(LRU *c, int cap) {
    memset(c, 0, sizeof(*c));
    c->cap = cap; c->head = c->tail = -1;
    for (int i = 0; i < MAXP; i++) { c->rprev[i] = c->rnext[i] = -1; }
}
static int lru_access(LRU *c, int p) {
    c->st.accesses++;
    if (c->resident[p]) {
        list_unlink(c->rprev, c->rnext, &c->head, &c->tail, p);
        list_push_tail(c->rprev, c->rnext, &c->head, &c->tail, p);
        c->st.hits++;
        return 1;
    }
    if (c->size >= c->cap) {
        int victim = c->head;
        list_unlink(c->rprev, c->rnext, &c->head, &c->tail, victim);
        c->resident[victim] = 0; c->size--;
    }
    c->resident[p] = 1; c->size++;
    list_push_tail(c->rprev, c->rnext, &c->head, &c->tail, p);
    c->st.faults++;
    return 0;
}

/* ------------------------------------------------------------------ *
 * CLOCK baseline (second chance).
 * ------------------------------------------------------------------ */
typedef struct {
    int cap, size, hand;
    int *frame; char *ref; int slot_of[MAXP];
    Stats st;
} CLOCK;

static void clock_init(CLOCK *c, int cap) {
    memset(c, 0, sizeof(*c));
    c->cap = cap; c->hand = 0;
    c->frame = malloc(sizeof(int) * cap);
    c->ref = malloc(cap);
    for (int i = 0; i < MAXP; i++) c->slot_of[i] = -1;
}
static int clock_access(CLOCK *c, int p) {
    c->st.accesses++;
    if (c->slot_of[p] != -1) { c->ref[c->slot_of[p]] = 1; c->st.hits++; return 1; }
    if (c->size < c->cap) {
        c->frame[c->size] = p; c->ref[c->size] = 1; c->slot_of[p] = c->size; c->size++;
    } else {
        for (;;) {
            if (!c->ref[c->hand]) {
                int victim = c->frame[c->hand];
                c->slot_of[victim] = -1;
                c->frame[c->hand] = p; c->ref[c->hand] = 1; c->slot_of[p] = c->hand;
                c->hand = (c->hand + 1) % c->cap;
                break;
            }
            c->ref[c->hand] = 0;
            c->hand = (c->hand + 1) % c->cap;
        }
    }
    c->st.faults++;
    return 0;
}

/* ------------------------------------------------------------------ *
 * Order-2 Markov predictor (hash map over (prev,curr) pairs).
 * ------------------------------------------------------------------ */
typedef struct {
    int *pages; int *counts; int n, cap; int total; int maxc;
} Succ;

#define HBITS 20
#define HSIZE (1 << HBITS)
typedef struct {
    int64_t *keys; Succ **vals; int occupied;
    int prev, curr;
} Markov;

static Markov *markov_new(void) {
    Markov *m = calloc(1, sizeof(Markov));
    m->keys = malloc(sizeof(int64_t) * HSIZE);
    m->vals = calloc(HSIZE, sizeof(Succ *));
    for (int i = 0; i < HSIZE; i++) m->keys[i] = -1;
    m->prev = m->curr = -1;
    return m;
}
static Succ *markov_bucket(Markov *m, int64_t key, int create) {
    uint64_t h = (uint64_t)key * 11400714819323198485ULL;
    int idx = (int)(h >> (64 - HBITS));
    while (m->keys[idx] != -1 && m->keys[idx] != key)
        idx = (idx + 1) & (HSIZE - 1);
    if (m->keys[idx] == key) return m->vals[idx];
    if (!create) return NULL;
    m->keys[idx] = key;
    Succ *s = calloc(1, sizeof(Succ));
    s->cap = 4; s->pages = malloc(sizeof(int) * s->cap); s->counts = malloc(sizeof(int) * s->cap);
    m->vals[idx] = s;
    return s;
}
static void markov_observe(Markov *m, int page) {
    if (m->prev != -1 && m->curr != -1) {
        int64_t key = (int64_t)m->prev * MAXP + m->curr;
        Succ *s = markov_bucket(m, key, 1);
        int found = -1;
        for (int i = 0; i < s->n; i++) if (s->pages[i] == page) { found = i; break; }
        if (found == -1) {
            if (s->n == s->cap) {
                s->cap *= 2;
                s->pages = realloc(s->pages, sizeof(int) * s->cap);
                s->counts = realloc(s->counts, sizeof(int) * s->cap);
            }
            s->pages[s->n] = page; s->counts[s->n] = 1; found = s->n; s->n++;
        } else {
            s->counts[found]++;
        }
        s->total++;
        if (s->counts[found] > s->maxc) s->maxc = s->counts[found];
    }
    m->prev = m->curr; m->curr = page;
}
static Succ *markov_current(Markov *m) {
    if (m->prev == -1 || m->curr == -1) return NULL;
    int64_t key = (int64_t)m->prev * MAXP + m->curr;
    return markov_bucket(m, key, 0);
}
static double markov_confidence(Markov *m) {
    Succ *s = markov_current(m);
    if (!s || s->total == 0) return 0.0;
    return (double)s->maxc / (double)s->total;
}
/* Fill out[] with up to k successors ranked by (count desc, page asc). */
static int markov_predict(Markov *m, int k, int *out) {
    Succ *s = markov_current(m);
    if (!s || s->n == 0) return 0;
    char used[64] = {0};  /* successor lists stay tiny in structured phases */
    int limit = s->n < 64 ? s->n : 64;
    int got = 0;
    for (int r = 0; r < k; r++) {
        int best = -1;
        for (int i = 0; i < limit; i++) {
            if (used[i]) continue;
            if (best == -1 || s->counts[i] > s->counts[best] ||
                (s->counts[i] == s->counts[best] && s->pages[i] < s->pages[best]))
                best = i;
        }
        if (best == -1) break;
        used[best] = 1; out[got++] = s->pages[best];
    }
    return got;
}

/* ------------------------------------------------------------------ *
 * Phase detector.
 * ------------------------------------------------------------------ */
typedef enum { PH_WARMUP, PH_SEQUENTIAL, PH_RANDOM, PH_LOOPING } Phase;

typedef struct {
    int cap, window, horizon, loop_fp;
    int last, steps, plus_one;
    int *stepbuf; int stephead, stepcount;   /* ring of +1 flags */
    int *longbuf; int longhead, longcount;    /* ring of recent pages */
    int lcount[MAXP]; int distinct;
    double seq_thr, loop_seq_thr;
} Phaser;

static void phaser_init(Phaser *p, int cap) {
    memset(p, 0, sizeof(*p));
    p->cap = cap; p->window = 32;
    p->horizon = (4 * cap > 256) ? 4 * cap : 256;
    p->loop_fp = (int)(1.5 * cap);
    p->seq_thr = 0.7; p->loop_seq_thr = 0.4;
    p->last = -1;
    p->stepbuf = calloc(p->window, sizeof(int));
    p->longbuf = malloc(sizeof(int) * p->horizon);
}
static Phase phaser_update(Phaser *p, int page) {
    if (p->last != -1) {
        int plus = (page - p->last == 1) ? 1 : 0;
        if (p->stepcount == p->window) { p->plus_one -= p->stepbuf[p->stephead]; }
        else { p->stepcount++; }
        p->stepbuf[p->stephead] = plus; p->plus_one += plus;
        p->stephead = (p->stephead + 1) % p->window;
    }
    p->last = page;

    if (p->longcount == p->horizon) {
        int old = p->longbuf[p->longhead];
        if (--p->lcount[old] == 0) p->distinct--;
    } else {
        p->longcount++;
    }
    p->longbuf[p->longhead] = page;
    if (p->lcount[page]++ == 0) p->distinct++;
    p->longhead = (p->longhead + 1) % p->horizon;

    if (p->stepcount < p->window - 1) return PH_WARMUP;
    double seq_ratio = (double)p->plus_one / (double)(p->stepcount ? p->stepcount : 1);
    if (seq_ratio >= p->loop_seq_thr && p->distinct <= p->loop_fp) return PH_LOOPING;
    if (seq_ratio >= p->seq_thr) return PH_SEQUENTIAL;
    return PH_RANDOM;
}

/* ------------------------------------------------------------------ *
 * Policy engine.
 * ------------------------------------------------------------------ */
typedef enum { EV_FIFO, EV_LRU, EV_MRU } Evict;
typedef struct { Evict evict; int prefetch; int degree; } Plan;

static Plan engine_plan(Phase ph) {
    Plan pl;
    if (ph == PH_SEQUENTIAL) { pl.evict = EV_FIFO; pl.prefetch = 1; pl.degree = 4; }
    else if (ph == PH_LOOPING) { pl.evict = EV_MRU; pl.prefetch = 1; pl.degree = 2; }
    else { pl.evict = EV_LRU; pl.prefetch = 0; pl.degree = 0; }
    return pl;
}

/* ------------------------------------------------------------------ *
 * Adaptive Markov Page Prefetcher.
 * ------------------------------------------------------------------ */
typedef struct {
    int cap, size;
    char resident[MAXP];
    char prefetched[MAXP];
    int rprev[MAXP], rnext[MAXP], rhead, rtail;   /* recency: head LRU, tail MRU */
    int fnext[MAXP], fprev[MAXP], fhead, ftail;   /* insertion order for FIFO */
    Markov *mk; Phaser ph; Stats st;
    double min_conf;
} AMPP;

static void ampp_init(AMPP *a, int cap) {
    memset(a, 0, sizeof(*a));
    a->cap = cap; a->rhead = a->rtail = a->fhead = a->ftail = -1;
    a->min_conf = 0.5;
    for (int i = 0; i < MAXP; i++) { a->rprev[i] = a->rnext[i] = a->fprev[i] = a->fnext[i] = -1; }
    a->mk = markov_new();
    phaser_init(&a->ph, cap);
}

static int in_set(const int *arr, int n, int p) {
    for (int i = 0; i < n; i++) if (arr[i] == p) return 1;
    return 0;
}

static int ampp_choose_victim(AMPP *a, Evict ev, const int *protect, int np) {
    if (ev == EV_FIFO) {
        int cur = a->fhead;
        while (cur != -1) { if (!in_set(protect, np, cur)) return cur; cur = a->fnext[cur]; }
        return -1;
    }
    if (ev == EV_LRU) {
        int cur = a->rhead;
        while (cur != -1) { if (!in_set(protect, np, cur)) return cur; cur = a->rnext[cur]; }
        return -1;
    }
    /* MRU */
    int cur = a->rtail;
    while (cur != -1) { if (!in_set(protect, np, cur)) return cur; cur = a->rprev[cur]; }
    return -1;
}

static void ampp_remove(AMPP *a, int victim) {
    list_unlink(a->rprev, a->rnext, &a->rhead, &a->rtail, victim);
    list_unlink(a->fprev, a->fnext, &a->fhead, &a->ftail, victim);
    a->resident[victim] = 0; a->prefetched[victim] = 0; a->size--;
}

/* Insert page; evict by ev if full (never evicting a protected page).
 * Returns victim page or -1. Returns -2 if no room (all protected). */
static int ampp_load(AMPP *a, int page, Evict ev, const int *protect, int np) {
    if (a->resident[page]) {
        list_unlink(a->rprev, a->rnext, &a->rhead, &a->rtail, page);
        list_push_tail(a->rprev, a->rnext, &a->rhead, &a->rtail, page);
        return -1;
    }
    int victim = -1;
    if (a->size >= a->cap) {
        victim = ampp_choose_victim(a, ev, protect, np);
        if (victim == -1) return -2;
        ampp_remove(a, victim);
    }
    a->resident[page] = 1; a->size++;
    list_push_tail(a->rprev, a->rnext, &a->rhead, &a->rtail, page);
    list_push_tail(a->fprev, a->fnext, &a->fhead, &a->ftail, page);
    return victim;
}

static int ampp_access(AMPP *a, int page) {
    Phase ph = phaser_update(&a->ph, page);
    Plan pl = engine_plan(ph);
    markov_observe(a->mk, page);
    a->st.accesses++;

    int hit;
    if (a->resident[page]) {
        list_unlink(a->rprev, a->rnext, &a->rhead, &a->rtail, page);
        list_push_tail(a->rprev, a->rnext, &a->rhead, &a->rtail, page);
        a->st.hits++;
        if (a->prefetched[page]) { a->st.prefetch_hits++; a->prefetched[page] = 0; }
        hit = 1;
    } else {
        ampp_load(a, page, pl.evict, NULL, 0);
        a->prefetched[page] = 0;
        a->st.faults++;
        hit = 0;
    }

    if (pl.prefetch && markov_confidence(a->mk) >= a->min_conf) {
        int preds[8];
        int k = markov_predict(a->mk, pl.degree, preds);
        int protect[16]; int np = 0;
        protect[np++] = page;
        for (int i = 0; i < k; i++) {
            int q = preds[i];
            if (a->resident[q]) continue;
            int victim = ampp_load(a, q, pl.evict, protect, np);
            if (victim == -2) break;
            if (victim != -1) a->prefetched[victim] = 0;
            a->prefetched[q] = 1;
            a->st.prefetches++;
            if (np < 16) protect[np++] = q;
        }
    }
    return hit;
}

/* ------------------------------------------------------------------ *
 * Harness.
 * ------------------------------------------------------------------ */
static const char *WL_NAME[4] = {"SEQUENTIAL", "RANDOM", "LOOPING", "MIXED"};

static void run_workload(Workload w, int cap, int length, unsigned seed) {
    int *trace = gen_trace(w, length, seed);

    LRU lru; lru_init(&lru, cap);
    CLOCK clk; clock_init(&clk, cap);
    AMPP *amp = malloc(sizeof(AMPP)); ampp_init(amp, cap);

    for (int i = 0; i < length; i++) lru_access(&lru, trace[i]);
    for (int i = 0; i < length; i++) clock_access(&clk, trace[i]);
    for (int i = 0; i < length; i++) ampp_access(amp, trace[i]);

    long lru_f = lru.st.faults ? lru.st.faults : 1;
    printf("\n%s  (cache=%d, accesses=%d, seed=%u)\n", WL_NAME[w], cap, length, seed);
    printf("  %-8s %10s %9s %10s\n", "policy", "hit rate", "faults", "vs LRU");
    printf("  ------------------------------------------\n");
    printf("  %-8s %9.1f%% %9ld %10s\n", "LRU", hit_rate(&lru.st) * 100, lru.st.faults, "--");
    printf("  %-8s %9.1f%% %9ld %9.1f%%\n", "CLOCK", hit_rate(&clk.st) * 100, clk.st.faults,
           (double)(lru_f - clk.st.faults) / lru_f * 100);
    printf("  %-8s %9.1f%% %9ld %9.1f%%\n", "AMPP", hit_rate(&amp->st) * 100, amp->st.faults,
           (double)(lru_f - amp->st.faults) / lru_f * 100);

    free(trace); free(amp);
}

int main(void) {
    int cap = 100, length = 20000; unsigned seed = 1234;
    printf("Adaptive Markov Page Prefetcher -- C core\n");
    run_workload(W_SEQUENTIAL, cap, length, seed);
    run_workload(W_RANDOM, cap, length, seed);
    run_workload(W_LOOPING, cap, length, seed);
    run_workload(W_MIXED, cap, length, seed);
    return 0;
}
