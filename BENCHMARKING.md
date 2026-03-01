# Flow - LLM Benchmarking Guide

Performance testing for Nemotron-3-Nano LLM before production deployment.

## Key Metrics

### TTFT (Time To First Token)
- **Definition**: Time from request submission to first token received
- **Target**: < 100ms for production
- **Why it matters**: Callers will hang up if there's dead air > 200ms

### TPS (Tokens Per Second)
- **Definition**: Generation speed after first token
- **Target**: > 20 TPS for production, > 30 TPS excellent
- **Why it matters**: Determines how fast the AI "speaks"

### Total Latency
- **Target**: < 500ms for 50-token response
- **Complete E2E**: < 250ms (including ASR + TTS)

## Running Benchmarks

### Option 1: Python Benchmark (Recommended)

```bash
cd ~/telephony-stack

# Basic benchmark (5 runs, 5 prompts)
python scripts/benchmark-nemotron.py

# More runs for statistical significance
python scripts/benchmark-nemotron.py --runs 10

# Custom prompt
python scripts/benchmark-nemotron.py --prompt "Explain machine learning"

# Different token count
python scripts/benchmark-nemotron.py --max-tokens 50

# Different endpoint
python scripts/benchmark-nemotron.py --url http://other-host:8000
```

### Option 2: Bash Benchmark

```bash
cd ~/telephony-stack
./scripts/benchmark-nemotron.sh

# With more runs
NUM_RUNS=10 ./scripts/benchmark-nemotron.sh
```

## Expected Results

### DGX Spark (GB10) with NVFP4

| Configuration | TTFT | TPS | Status |
|--------------|------|-----|--------|
| Nemotron-3-Nano, modelopt_fp4 | 50-80ms | 25-35 | ✅ Production Ready |
| With reasoning disabled | 40-60ms | 28-40 | ✅ Excellent |
| Temperature 0.3 (vs 0.7) | 30-50ms | 30-45 | ✅ Optimized |

### What Affects Performance

**GPU Utilization**:
```bash
watch -n 1 nvidia-smi
```
- Should see ~20% GPU usage for Nemotron
- Mamba has no KV cache, so memory stays flat

**Temperature**:
- Lower = faster (less sampling randomness)
- 0.3 = fast, deterministic
- 0.7 = slower, more creative

**Quantization**:
- modelopt_fp4 = fastest, some quality loss
- bfloat16 = slower, best quality

**Reasoning**:
- --no-enable-reasoning = faster TTFT
- Reasoning adds 50-200ms overhead

## Interpreting Results

### ✅ Production Ready
```
TTFT: 50ms average
TPS:  30
Assessment: Excellent for telephony
```

### ⚠️ Acceptable with Monitoring
```
TTFT: 150ms average  
TPS:  15
Assessment: May cause slight delay, monitor closely
```

### ❌ Needs Optimization
```
TTFT: 300ms average
TPS:  8
Assessment: Callers will notice delay, optimize before production
```

## Troubleshooting Poor Performance

### High TTFT (> 200ms)

**Check 1: GPU Warming**
- First request after idle may be slow
- Run warm-up: `python scripts/benchmark-nemotron.py --runs 3`

**Check 2: Reasoning Enabled**
- Verify: `--no-enable-reasoning` in start-nemotron.sh
- Check logs for reasoning tokens

**Check 3: Model Loading**
- Check if model is fully loaded in GPU
- Look for "Loading weights" in logs

### Low TPS (< 15)

**Check 1: GPU Utilization**
```bash
nvidia-smi dmon -s u
```
- Should see high "sm" (streaming multiprocessor) usage

**Check 2: Batch Size**
- Single request = batch size 1
- TPS improves with concurrent requests

**Check 3: Quantization**
- modelopt_fp4 should be fast
- If using bfloat16, expect 2x slower

## Production Checklist

Before deploying to production:

- [ ] Run benchmark with 10+ iterations
- [ ] TTFT consistently < 100ms
- [ ] TPS consistently > 20
- [ ] GPU utilization stable at ~20%
- [ ] No memory leaks over extended run
- [ ] Tested with voice cloning enabled
- [ ] Tested with concurrent calls (2-3)

## Automated CI/CD Testing

Add to your CI pipeline:

```yaml
# .github/workflows/benchmark.yml (example)
- name: Benchmark LLM
  run: |
    ./scripts/start-nemotron.sh &
    sleep 30  # Wait for startup
    python scripts/benchmark-nemotron.py --runs 10
    pkill -f nemotron
```

## Comparing Configurations

Run benchmarks with different settings:

```bash
# Test 1: Current config
python scripts/benchmark-nemotron.py --runs 5

# Test 2: Lower temperature (edit start-nemotron.sh, restart)
# Change: --temperature 0.3
python scripts/benchmark-nemotron.py --runs 5

# Compare results
```

## Files

```
scripts/
├── benchmark-nemotron.py    # Python benchmark (recommended)
├── benchmark-nemotron.sh    # Bash benchmark (alternative)
└── start-nemotron.sh        # LLM launch configuration

BENCHMARKING.md              # This file
```

## Next Steps

1. **Run benchmark**: `python scripts/benchmark-nemotron.py`
2. **Check results**: Verify TTFT < 100ms, TPS > 20
3. **Optimize if needed**: Adjust temperature, verify reasoning disabled
4. **Load test**: Test with concurrent calls
5. **Production**: Deploy with monitoring

---

**Target for Production**:
- TTFT: < 100ms ✅
- TPS: > 20 ✅
- E2E (ASR+LLM+TTS): < 250ms ✅
