import sys, types, time, random

def stub(name, attrs):
    m = types.ModuleType(name)
    for a in attrs:
        setattr(m, a, type(a, (object,), {"__init__": lambda self, *a, **k: None}))
    sys.modules[name] = m

pkg = types.ModuleType("rich"); pkg.__path__ = []
sys.modules["rich"] = pkg
stub("httpx", ["AsyncClient", "Timeout"])
stub("rich.console", ["Console"]); stub("rich.layout", ["Layout"])
stub("rich.live", ["Live"]); stub("rich.panel", ["Panel"])
stub("rich.progress", ["BarColumn", "Progress", "TextColumn", "TimeElapsedColumn"])
stub("rich.table", ["Table"]); stub("rich.text", ["Text"])

sys.path.insert(0, "/home/dsh/strix-halo-r9700-llm-builds/llm-inference-bench")
import llm_decode_bench as B

OLD_SENTENCES = [
    "The history of European architecture spans thousands of years and encompasses a wide variety of styles and movements.",
    "From the ancient Greek temples to the Gothic cathedrals of the Middle Ages, each era has left its distinctive mark on the built environment.",
    "The Renaissance brought a renewed interest in classical forms, while the Baroque period introduced dramatic ornamentation and grandeur.",
    "In the modern era, architects have experimented with new materials such as steel, glass, and reinforced concrete.",
    "The development of skyscrapers in the late 19th century transformed urban landscapes around the world.",
    "Sustainable architecture has become increasingly important as societies grapple with climate change and resource depletion.",
    "The principles of good design include functionality, durability, and aesthetic appeal.",
    "Urban planning plays a crucial role in shaping how cities develop and how their inhabitants experience daily life.",
    "Public spaces such as parks, plazas, and waterfronts contribute significantly to the quality of urban living.",
    "The integration of technology into building design has opened up new possibilities for energy efficiency and comfort.",
    "Historical preservation efforts seek to maintain the cultural heritage embodied in older structures.",
    "The relationship between architecture and nature has been explored by many influential designers throughout history.",
    "Building codes and regulations ensure that structures meet minimum standards for safety and accessibility.",
    "The choice of materials in construction affects not only the appearance of a building but also its environmental impact.",
    "Innovative structural engineering techniques have made it possible to create buildings of unprecedented scale and complexity.",
    "The study of vernacular architecture reveals how different cultures have adapted their building practices to local conditions.",
    "Interior design complements architecture by addressing the arrangement and decoration of interior spaces.",
    "Landscape architecture deals with the design of outdoor areas, landmarks, and structures to achieve environmental or aesthetic outcomes.",
    "The concept of smart cities integrates information technology with urban infrastructure to improve efficiency and quality of life.",
    "Affordable housing remains one of the most pressing challenges facing urban planners and policymakers worldwide.",
]

def old_gen(target_tokens):
    target = target_tokens * 4
    out, n, i = [], 0, 0
    while n < target:
        out.append(OLD_SENTENCES[i % len(OLD_SENTENCES)])
        n += len(out[-1]) + 1
        i += 1
    return " ".join(out)

def trigrams(text):
    w = text.split()
    return {tuple(w[i:i+3]) for i in range(len(w)-2)}, max(len(w)-2, 0)

ATOMS = ("proj", "blk", "kt", "hit", "buf", "copy", "sm_", "arg", "tmp", "f32", "gfx", "num", "cnt", "ptr")
def atoms(n, seed=7):
    r = random.Random(seed)
    return " ".join(r.choice(ATOMS) + str(r.randrange(1 << 24)) for _ in range(n))

for ctx in (8192, 131072, 262144):
    t0 = time.time(); o = old_gen(ctx); t_old = time.time() - t0
    t0 = time.time(); n = B.generate_padding_text(ctx, seed=f"bench:{ctx}"); t_new = time.time() - t0
    od, ot = trigrams(o)
    nd, nt = trigrams(n)
    print(f"ctx={ctx:>7}   OLD distinct_trigrams={len(od):>7} / {ot:>7} total  ({100*len(od)/ot:5.1f}% distinct)  gen={t_old:.2f}s")
    print(f"{'':>12} NEW distinct_trigrams={len(nd):>7} / {nt:>7} total  ({100*len(nd)/nt:5.1f}% distinct)  gen={t_new:.2f}s")

print()
print("determinism (same seed, same ctx):", B.generate_padding_text(8192, seed="bench:8192") == B.generate_padding_text(8192, seed="bench:8192"))
print("per-context distinctness:", B.generate_padding_text(8192, seed="bench:8192") != B.generate_padding_text(8192, seed="bench:16384"))
print("warmup seed distinct from ctx seed:", B.generate_padding_text(8192, seed="bench:warmup") != B.generate_padding_text(8192, seed="bench:8192"))
print()
# Token count sanity: CHARS_PER_TOKEN=4 is an approximation; report actual char ratio
for ctx in (8192, 262144):
    n = B.generate_padding_text(ctx, seed=f"bench:{ctx}")
    print(f"ctx={ctx:>7} requested ~{ctx*4} chars, got {len(n)} chars ({len(n)/ctx:.2f} chars/token)")
print()
# Adjacent-duplicate sentence check
s = B.generate_padding_text(16384, seed="bench:16384").split(" . ")
print("immediate sentence repeats (new):", sum(1 for i in range(len(s)-1) if s[i] == s[i+1]))
s2 = old_gen(16384).split(" . ")
print("immediate sentence repeats (old):", sum(1 for i in range(len(s2)-1) if s2[i] == s2[i+1]))
