/*
 * measure_random_read_latency.c — QD1 random 4K O_DIRECT read latency.
 *
 * Why this exists: qwen3.8-flash-next's ~26.8 GiB PLE / n-gram table is
 * mmap-backed on CPU with whole-file prefetch deliberately disabled (see
 * docker/qwen4exp-strix-halo-mtp/llama-cpp-qwen38-per-buffer-mmap.patch), so
 * its rows are demand-faulted. Whether that gather is a significant share of
 * the ~2.58 ms/token constant prefill floor measured in
 * knowledge/research/2026-09-27-flashnext-prefill-constant-floor.md turns
 * entirely on what one cold row read costs. That is a property of the box's
 * storage, not of the model, so it can be measured with nothing running.
 *
 * 2026-09-27 result on local-ai-machine, against the 49.8 GB shard 2 of the
 * UD-IQ4_XS model on /dev/nvme0n1p2 (ext4, root fs):
 *     mean 204 us, p50 202 us, p90 226 us, p99 360 us, max 1004 us
 *
 * The interpretation that matters: the gather is 16 rows per token, so 16
 * serialised cold reads would cost ~3.2 ms/token — more than the entire
 * measured floor. A 388 tok/s prefill is therefore incompatible with "16
 * serialised cold row reads per token" on this box.
 *
 * Build and run (read-only; touches no data, writes nothing):
 *     gcc -O2 -o /tmp/rdlat measure_random_read_latency.c
 *     /tmp/rdlat /var/lib/ai-models/<model-dir>/<shard>.gguf 2000
 *
 * O_DIRECT is used so reads always reach the device and are never served from
 * the page cache, and so this does not evict the running model's cached pages
 * the way drop_caches would.
 *
 * Caveat: this measures raw device latency at QD1 from this host's CPU. It is a
 * bound on the cost of one cold row, not a measurement of what the model's
 * gather actually pays — see the caveats in the research note.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <string.h>

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

static double *L;
static int cmp(const void *a, const void *b) {
    double x = *(double *)a, y = *(double *)b;
    return (x > y) - (x < y);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <file> [samples]\n", argv[0]);
        return 2;
    }
    const char *path = argv[1];
    int n = argc > 2 ? atoi(argv[2]) : 2000;

    int fd = open(path, O_RDONLY | O_DIRECT);
    if (fd < 0) { perror("open (O_DIRECT needs a real file on a real fs)"); return 1; }

    off_t size = lseek(fd, 0, SEEK_END);
    if (size <= 0) { perror("lseek"); return 1; }

    void *buf;
    if (posix_memalign(&buf, 4096, 4096)) { perror("posix_memalign"); return 1; }
    memset(buf, 0, 4096);

    L = malloc(sizeof(double) * n);
    if (!L) { perror("malloc"); return 1; }

    /* xorshift64 — deliberately not rand(), so offsets are reproducible. */
    unsigned long long x = 88172645463325252ULL;
    long long maxblk = (size / 4096) - 1;
    int ok = 0;
    for (int i = 0; i < n; i++) {
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        off_t off = (off_t)((x >> 11) % maxblk) * 4096;
        double t0 = now_s();
        ssize_t r = pread(fd, buf, 4096, off);
        double t1 = now_s();
        if (r == 4096) L[ok++] = (t1 - t0) * 1e6;
    }
    if (ok == 0) { fprintf(stderr, "no successful reads (O_DIRECT alignment?)\n"); return 1; }

    qsort(L, ok, sizeof(double), cmp);
    double sum = 0;
    for (int i = 0; i < ok; i++) sum += L[i];

    printf("file=%s size=%.1fGB samples=%d\n", path, size / 1e9, ok);
    printf("random 4K O_DIRECT QD1 latency (us): mean=%.0f p50=%.0f p90=%.0f p99=%.0f max=%.0f\n",
           sum / ok, L[ok / 2], L[(int)(ok * 0.9)], L[(int)(ok * 0.99)], L[ok - 1]);
    return 0;
}
