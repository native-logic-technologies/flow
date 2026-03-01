#!/usr/bin/env python3
"""
Nemotron LLM Performance Benchmark
Measures TTFT (Time To First Token) and TPS (Tokens Per Second)

Usage:
    python benchmark-nemotron.py [--runs 5] [--max-tokens 100]
"""

import argparse
import json
import time
import statistics
from typing import List, Dict
import requests


class LLMBenchmark:
    """Benchmark Nemotron LLM performance"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.chat_url = f"{base_url}/v1/chat/completions"
        
    def check_health(self) -> bool:
        """Check if LLM service is running"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except Exception as e:
            print(f"Health check failed: {e}")
            return False
    
    def benchmark_prompt(self, prompt: str, max_tokens: int = 100) -> Dict:
        """Run single benchmark and return metrics"""
        
        payload = {
            "model": "/home/phil/telephony-stack/models/llm/nemotron-3-nano-30b-nvfp4",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant. Be concise."},
                {"role": "user", "content": prompt}
            ],
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "skip_special_tokens": True,
            "stop": ["<think>", "</think>"]
        }
        
        start_time = time.perf_counter()
        first_token_time = None
        token_count = 0
        
        try:
            response = requests.post(
                self.chat_url,
                json=payload,
                stream=True,
                timeout=60
            )
            response.raise_for_status()
            
            for line in response.iter_lines():
                if not line:
                    continue
                    
                line = line.decode('utf-8')
                
                # Skip SSE prefix
                if line.startswith('data: '):
                    line = line[6:]
                
                if line == '[DONE]':
                    break
                
                try:
                    data = json.loads(line)
                    if 'choices' in data and len(data['choices']) > 0:
                        delta = data['choices'][0].get('delta', {})
                        if 'content' in delta and delta['content']:
                            token_count += 1
                            
                            # Record time of first token
                            if first_token_time is None:
                                first_token_time = time.perf_counter()
                except json.JSONDecodeError:
                    continue
            
            end_time = time.perf_counter()
            
            # Calculate metrics
            total_time_ms = (end_time - start_time) * 1000
            ttft_ms = (first_token_time - start_time) * 1000 if first_token_time else 0
            
            # Calculate TPS (excluding TTFT for generation speed)
            generation_time_ms = total_time_ms - ttft_ms
            tps = (token_count / generation_time_ms * 1000) if generation_time_ms > 0 else 0
            
            return {
                'ttft_ms': ttft_ms,
                'total_time_ms': total_time_ms,
                'token_count': token_count,
                'tps': tps,
                'success': True
            }
            
        except Exception as e:
            print(f"  Error during benchmark: {e}")
            return {
                'ttft_ms': 0,
                'total_time_ms': 0,
                'token_count': 0,
                'tps': 0,
                'success': False,
                'error': str(e)
            }
    
    def run_benchmarks(self, prompts: List[str], num_runs: int = 5, max_tokens: int = 100):
        """Run benchmarks for multiple prompts"""
        
        print("╔════════════════════════════════════════════════════════════════════╗")
        print("║  Nemotron-3-Nano LLM Performance Benchmark                         ║")
        print("╚════════════════════════════════════════════════════════════════════╝")
        print()
        print(f"Configuration:")
        print(f"  LLM Endpoint: {self.base_url}")
        print(f"  Test Runs per Prompt: {num_runs}")
        print(f"  Max Tokens: {max_tokens}")
        print(f"  Model: Nemotron-3-Nano-30B-A3B-NVFP4")
        print()
        
        # Check health
        if not self.check_health():
            print("✗ ERROR: Nemotron LLM not responding")
            print(f"  Please start the LLM service: ./scripts/start-nemotron.sh")
            return
        
        print("✓ LLM is accessible")
        print()
        
        all_results = []
        
        for prompt_idx, prompt in enumerate(prompts, 1):
            print(f"Prompt {prompt_idx}/{len(prompts)}: \"{prompt[:60]}...\"")
            print()
            
            prompt_results = []
            
            for run in range(1, num_runs + 1):
                print(f"  Run {run}/{num_runs}: ", end='', flush=True)
                result = self.benchmark_prompt(prompt, max_tokens)
                
                if result['success']:
                    prompt_results.append(result)
                    print(f"TTFT={result['ttft_ms']:.1f}ms | "
                          f"Tokens={result['token_count']} | "
                          f"TPS={result['tps']:.1f} | "
                          f"Total={result['total_time_ms']:.1f}ms")
                else:
                    print(f"FAILED: {result.get('error', 'Unknown error')}")
                
                time.sleep(0.5)  # Brief pause between runs
            
            all_results.extend(prompt_results)
            print()
        
        # Calculate statistics
        if not all_results:
            print("No successful benchmarks to analyze")
            return
        
        ttft_values = [r['ttft_ms'] for r in all_results]
        tps_values = [r['tps'] for r in all_results]
        total_time_values = [r['total_time_ms'] for r in all_results]
        token_counts = [r['token_count'] for r in all_results]
        
        print("═════════════════════════════════════════════════════════════════════")
        print("                    BENCHMARK RESULTS SUMMARY")
        print("═════════════════════════════════════════════════════════════════════")
        print()
        
        print("Time To First Token (TTFT):")
        print(f"  Average: {statistics.mean(ttft_values):.2f} ms")
        print(f"  Median:  {statistics.median(ttft_values):.2f} ms")
        print(f"  Min:     {min(ttft_values):.2f} ms")
        print(f"  Max:     {max(ttft_values):.2f} ms")
        print(f"  Stdev:   {statistics.stdev(ttft_values):.2f} ms" if len(ttft_values) > 1 else "  Stdev:   N/A")
        print()
        
        print("Tokens Per Second (TPS):")
        print(f"  Average: {statistics.mean(tps_values):.2f}")
        print(f"  Median:  {statistics.median(tps_values):.2f}")
        print(f"  Min:     {min(tps_values):.2f}")
        print(f"  Max:     {max(tps_values):.2f}")
        print(f"  Stdev:   {statistics.stdev(tps_values):.2f}" if len(tps_values) > 1 else "  Stdev:   N/A")
        print()
        
        print("Total Generation Time:")
        print(f"  Average: {statistics.mean(total_time_values):.2f} ms")
        print(f"  Median:  {statistics.median(total_time_values):.2f} ms")
        print(f"  Min:     {min(total_time_values):.2f} ms")
        print(f"  Max:     {max(total_time_values):.2f} ms")
        print()
        
        print("Total Tokens Generated:")
        print(f"  Average: {statistics.mean(token_counts):.1f}")
        print(f"  Median:  {statistics.median(token_counts):.1f}")
        print()
        
        print("═════════════════════════════════════════════════════════════════════")
        print("                    PRODUCTION READINESS CHECK")
        print("═════════════════════════════════════════════════════════════════════")
        print()
        
        ttft_avg = statistics.mean(ttft_values)
        tps_avg = statistics.mean(tps_values)
        
        # TTFT Check
        print(f"Target TTFT: < 100ms    | Actual: {ttft_avg:.2f}ms")
        if ttft_avg < 100:
            print("  ✅ PASS - Excellent first-token latency")
        elif ttft_avg < 200:
            print("  ⚠️  WARNING - Acceptable but could be optimized")
        else:
            print("  ❌ FAIL - Consider: Lower temperature, disable reasoning, check GPU")
        print()
        
        # TPS Check
        print(f"Target TPS: > 20        | Actual: {tps_avg:.2f}")
        if tps_avg > 30:
            print("  ✅ PASS - Excellent throughput")
        elif tps_avg > 20:
            print("  ✅ PASS - Good throughput")
        elif tps_avg > 10:
            print("  ⚠️  WARNING - Acceptable but could be optimized")
        else:
            print("  ❌ FAIL - Check GPU utilization, batch size, quantization settings")
        print()
        
        # Overall assessment
        if ttft_avg < 100 and tps_avg > 20:
            print("🎉 OVERALL: Production Ready!")
        elif ttft_avg < 200 and tps_avg > 10:
            print("✓ OVERALL: Acceptable for production with monitoring")
        else:
            print("⚠️  OVERALL: Needs optimization before production")
        
        print()


def main():
    parser = argparse.ArgumentParser(description='Benchmark Nemotron LLM Performance')
    parser.add_argument('--url', default='http://localhost:8000', help='LLM base URL')
    parser.add_argument('--runs', type=int, default=5, help='Number of runs per prompt')
    parser.add_argument('--max-tokens', type=int, default=100, help='Max tokens to generate')
    parser.add_argument('--prompt', type=str, help='Single custom prompt to test')
    
    args = parser.parse_args()
    
    benchmark = LLMBenchmark(args.url)
    
    if args.prompt:
        prompts = [args.prompt]
    else:
        prompts = [
            "Say hello and introduce yourself briefly.",
            "Explain quantum computing in simple terms.",
            "What are the main benefits of renewable energy?",
            "Write a haiku about technology.",
            "Describe the process of photosynthesis.",
        ]
    
    benchmark.run_benchmarks(prompts, args.runs, args.max_tokens)


if __name__ == '__main__':
    main()
