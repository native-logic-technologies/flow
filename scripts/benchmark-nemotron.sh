#!/bin/bash
# =============================================================================
# Nemotron LLM Performance Benchmark
# Measures TTFT (Time To First Token) and TPS (Tokens Per Second)
# =============================================================================

set -e

LLM_URL="${LLM_URL:-http://localhost:8000/v1/chat/completions}"
NUM_RUNS="${NUM_RUNS:-5}"

echo "╔════════════════════════════════════════════════════════════════════╗"
echo "║  Nemotron-3-Nano LLM Performance Benchmark                         ║"
echo "╚════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Configuration:"
echo "  LLM Endpoint: $LLM_URL"
echo "  Test Runs: $NUM_RUNS"
echo "  Model: Nemotron-3-Nano-30B-A3B-NVFP4"
echo "  Quantization: modelopt_fp4"
echo ""

# Check if LLM is running
if ! curl -s "$LLM_URL" > /dev/null 2>&1; then
    echo "✗ ERROR: Nemotron LLM not responding on $LLM_URL"
    echo "  Please start the LLM service first:"
    echo "  ./scripts/start-nemotron.sh"
    exit 1
fi

echo "✓ LLM is accessible"
echo ""

# Test prompts of varying complexity
PROMPTS=(
    "Say hello."
    "Explain quantum computing in simple terms."
    "Write a short poem about technology."
    "What are the benefits of renewable energy? Discuss three main points."
)

# Results storage
declare -a TTFT_RESULTS
declare -a TPS_RESULTS
declare -a TOTAL_TIME_RESULTS
declare -a TOTAL_TOKENS_RESULTS

run_benchmark() {
    local prompt="$1"
    local run_num="$2"
    
    echo "Run $run_num: Testing prompt: \"${prompt:0:50}...\""
    
    # Create temp files for timing
    local start_time_file=$(mktemp)
    local first_token_file=$(mktemp)
    local end_time_file=$(mktemp)
    local token_count_file=$(mktemp)
    
    # Record start time
    date +%s%N > "$start_time_file"
    
    # Make streaming request and measure
    local first_token_received=false
    local token_count=0
    
    curl -s -N -X POST "$LLM_URL" \
        -H "Content-Type: application/json" \
        -d "{
            \"model\": \"/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4\",
            \"messages\": [
                {\"role\": \"system\", \"content\": \"You are a helpful assistant. Be concise.\"},
                {\"role\": \"user\", \"content\": \"$prompt\"}
            ],
            \"stream\": true,
            \"max_tokens\": 100,
            \"temperature\": 0.7
        }" | while IFS= read -r line; do
            # Check for first token
            if [ "$first_token_received" = false ] && [[ "$line" == *"content"* ]];
 then
                date +%s%N > "$first_token_file"
                first_token_received=true
            fi
            
            # Count tokens (approximate by counting content fields)
            if [[ "$line" == *"content"* ]]; then
                token_count=$((token_count + 1))
                echo "$token_count" > "$token_count_file"
            fi
            
            # Check for completion
            if [[ "$line" == *"[DONE]"* ]]; then
                date +%s%N > "$end_time_file"
            fi
        done
    
    # If end time wasn't captured, record it now
    if [ ! -f "$end_time_file" ]; then
        date +%s%N > "$end_time_file"
    fi
    
    # Read timings
    local start_time=$(cat "$start_time_file")
    local first_token_time=$(cat "$first_token_file" 2>/dev/null || echo "$start_time")
    local end_time=$(cat "$end_time_file")
    local total_tokens=$(cat "$token_count_file" 2>/dev/null || echo "0")
    
    # Calculate TTFT (Time To First Token) in milliseconds
    local ttft_ms=$(( (first_token_time - start_time) / 1000000 ))
    
    # Calculate total time in milliseconds
    local total_ms=$(( (end_time - start_time) / 1000000 ))
    
    # Calculate TPS (Tokens Per Second)
    local tps=0
    if [ "$total_ms" -gt 0 ] && [ "$total_tokens" -gt 0 ]; then
        tps=$(echo "scale=2; $total_tokens * 1000 / $total_ms" | bc 2>/dev/null || echo "0")
    fi
    
    # Cleanup
    rm -f "$start_time_file" "$first_token_file" "$end_time_file" "$token_count_file"
    
    # Store results
    TTFT_RESULTS+=($ttft_ms)
    TPS_RESULTS+=($tps)
    TOTAL_TIME_RESULTS+=($total_ms)
    TOTAL_TOKENS_RESULTS+=($total_tokens)
    
    echo "    TTFT: ${ttft_ms}ms | Tokens: $total_tokens | TPS: $tps | Total: ${total_ms}ms"
}

# Run benchmarks for each prompt
echo "Starting benchmarks..."
echo "─────────────────────────────────────────────────────────────────────"
echo ""

for prompt in "${PROMPTS[@]}"; do
    echo "Prompt: \"$prompt\""
    echo ""
    
    for i in $(seq 1 $NUM_RUNS); do
        run_benchmark "$prompt" $i
        sleep 0.5  # Brief pause between runs
    done
    
    echo ""
done

# Calculate statistics
echo "═════════════════════════════════════════════════════════════════════"
echo "                    BENCHMARK RESULTS SUMMARY"
echo "═════════════════════════════════════════════════════════════════════"
echo ""

# Helper function to calculate average
calc_avg() {
    local arr=($@)
    local sum=0
    for val in "${arr[@]}"; do
        sum=$(echo "$sum + $val" | bc 2>/dev/null || echo "$sum")
    done
    local count=${#arr[@]}
    if [ $count -gt 0 ]; then
        echo "scale=2; $sum / $count" | bc 2>/dev/null || echo "N/A"
    else
        echo "N/A"
    fi
}

# Helper function to find min
calc_min() {
    local arr=($@)
    local min=${arr[0]}
    for val in "${arr[@]}"; do
        if [ $(echo "$val < $min" | bc 2>/dev/null || echo "0") -eq 1 ]; then
            min=$val
        fi
    done
    echo "$min"
}

# Helper function to find max
calc_max() {
    local arr=($@)
    local max=${arr[0]}
    for val in "${arr[@]}"; do
        if [ $(echo "$val > $max" | bc 2>/dev/null || echo "0") -eq 1 ]; then
            max=$val
        fi
    done
    echo "$max"
}

echo "Time To First Token (TTFT):"
echo "  Average: $(calc_avg ${TTFT_RESULTS[@]}) ms"
echo "  Min:     $(calc_min ${TTFT_RESULTS[@]}) ms"
echo "  Max:     $(calc_max ${TTFT_RESULTS[@]}) ms"
echo ""

echo "Tokens Per Second (TPS):"
echo "  Average: $(calc_avg ${TPS_RESULTS[@]})"
echo "  Min:     $(calc_min ${TPS_RESULTS[@]})"
echo "  Max:     $(calc_max ${TPS_RESULTS[@]})"
echo ""

echo "Total Generation Time:"
echo "  Average: $(calc_avg ${TOTAL_TIME_RESULTS[@]}) ms"
echo "  Min:     $(calc_min ${TOTAL_TIME_RESULTS[@]}) ms"
echo "  Max:     $(calc_max ${TOTAL_TIME_RESULTS[@]}) ms"
echo ""

echo "Total Tokens Generated:"
echo "  Average: $(calc_avg ${TOTAL_TOKENS_RESULTS[@]})"
echo ""

echo "═════════════════════════════════════════════════════════════════════"
echo "                    PRODUCTION READINESS CHECK"
echo "═════════════════════════════════════════════════════════════════════"
echo ""

# Check against targets
TTFT_AVG=$(calc_avg ${TTFT_RESULTS[@]})
TPS_AVG=$(calc_avg ${TPS_RESULTS[@]})

# Convert to integers for comparison
TTFT_INT=$(echo "$TTFT_AVG" | cut -d. -f1)
TPS_INT=$(echo "$TPS_AVG" | cut -d. -f1)

echo "Target TTFT: < 100ms    | Actual: ${TTFT_AVG}ms"
if [ "$TTFT_INT" -lt 100 ]; then
    echo "  ✅ PASS"
else
    echo "  ❌ FAIL - Consider: Lower temperature, disable reasoning, GPU optimization"
fi
echo ""

echo "Target TPS: > 20        | Actual: ${TPS_AVG}"
if [ "$TPS_INT" -gt 20 ]; then
    echo "  ✅ PASS"
else
    echo "  ❌ FAIL - Consider: Check GPU utilization, batch size, quantization"
fi
echo ""

echo "═════════════════════════════════════════════════════════════════════"
echo ""
echo "Benchmark complete! Run with different prompts or settings to compare."
echo ""
