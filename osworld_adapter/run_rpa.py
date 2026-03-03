#!/usr/bin/env python3
"""
OSWorld benchmark runner using our RPA agent.

Standalone script that:
1. Creates a DesktopEnv (Docker provider with KVM)
2. Loads task configs from OSWorld evaluation_examples
3. Runs our RPAAgent on each task
4. Evaluates and records results

Usage:
    cd /home/osworld
    source .venv/bin/activate
    python run_rpa.py --subset small --max_steps 15
    python run_rpa.py --domain chrome --max_steps 15
    python run_rpa.py --max_steps 15  # all domains
"""

import argparse
import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("run_rpa.log"),
    ]
)
logger = logging.getLogger("osworld.run_rpa")

# Add OSWorld to path
sys.path.insert(0, "/home/osworld")


def load_task_configs(task_ids, examples_dir="/home/osworld/evaluation_examples"):
    """Load task configs from evaluation_examples directory."""
    configs = []
    examples_path = Path(examples_dir)
    examples_subdir = examples_path / "examples"

    for task_id in task_ids:
        found = False

        # Primary: evaluation_examples/examples/<domain>/<task_id>.json
        if examples_subdir.exists():
            for domain_dir in examples_subdir.iterdir():
                if not domain_dir.is_dir():
                    continue
                task_file = domain_dir / f"{task_id}.json"
                if task_file.exists():
                    with open(task_file) as f:
                        config = json.load(f)
                    config["_domain"] = domain_dir.name
                    configs.append(config)
                    found = True
                    break

        if not found:
            logger.warning(f"Task config not found for {task_id}, skipping")
            configs.append({
                "id": task_id,
                "_domain": "unknown",
                "_missing": True,
            })

    return configs


def get_task_ids(subset="small", domain=None, test_file=None):
    """Get task IDs based on subset or domain filter."""
    if test_file:
        with open(test_file) as f:
            data = json.load(f)
    elif subset == "small":
        test_path = "/home/osworld/evaluation_examples/test_small.json"
        with open(test_path) as f:
            data = json.load(f)
    elif subset == "all":
        test_path = "/home/osworld/evaluation_examples/test_all.json"
        with open(test_path) as f:
            data = json.load(f)
    else:
        raise ValueError(f"Unknown subset: {subset}")

    task_ids = []
    domains_included = []

    for d, ids in data.items():
        if domain and d != domain:
            continue
        task_ids.extend(ids)
        domains_included.append(f"{d}({len(ids)})")

    logger.info(f"Loaded {len(task_ids)} tasks from: {', '.join(domains_included)}")
    return task_ids


def run_benchmark(args):
    """Main benchmark runner."""
    from desktop_env.desktop_env import DesktopEnv

    # Import our agent adapter
    from mm_agents.rpa_agent import RPAAgent

    # Get task IDs
    if args._specific_ids:
        task_ids = args._specific_ids
    else:
        task_ids = get_task_ids(
            subset=args.subset,
            domain=args.domain,
            test_file=args.test_file,
        )

    if not task_ids:
        logger.error("No tasks to run!")
        return

    # Create results directory
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path(f"/home/osworld/results/rpa_agent_{timestamp}")
    results_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Results directory: {results_dir}")

    # Create environment
    logger.info("Creating DesktopEnv with Docker provider...")
    env = DesktopEnv(
        provider_name="docker",
        os_type="ubuntu",
        action_space="pyautogui",
        headless=True,
        require_a11y_tree=not args.no_a11y,
    )
    logger.info(f"Environment created. VM IP: {env.vm_ip}")

    # Create agent
    agent = RPAAgent(
        vlm_base_url=args.vlm_url,
        vlm_api_key=args.vlm_api_key,
        vlm_model=args.vlm_model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        max_trajectory_length=args.trajectory_length,
        vlm_max_edge=args.vlm_max_edge,
        vlm_image_quality=args.vlm_image_quality,
        client_password=args.vm_password,
    )

    # Track results
    scores = []
    results = []
    total_start = time.time()

    for idx, task_id in enumerate(task_ids):
        logger.info(f"\n{'='*60}")
        logger.info(f"Task {idx+1}/{len(task_ids)}: {task_id}")
        logger.info(f"{'='*60}")

        # Create task result directory
        task_result_dir = results_dir / task_id
        task_result_dir.mkdir(parents=True, exist_ok=True)

        # Load task config
        task_configs = load_task_configs([task_id])
        if not task_configs or task_configs[0].get("_missing"):
            logger.error(f"Could not load config for task {task_id}, skipping")
            results.append({
                "task_id": task_id,
                "score": 0.0,
                "status": "config_missing",
                "steps": 0,
            })
            continue

        example = task_configs[0]
        domain = example.get("_domain", "unknown")
        instruction = example.get("instruction", "")
        logger.info(f"Domain: {domain}")
        logger.info(f"Instruction: {instruction[:100]}...")

        task_start = time.time()

        try:
            # Reset environment with task config
            logger.info("Resetting environment...")
            env.reset(task_config=example)

            # Reset agent
            agent.reset()

            # Wait for environment to be ready
            wait_time = args.env_wait
            logger.info(f"Waiting {wait_time}s for environment to be ready...")
            time.sleep(wait_time)

            # Get initial observation
            obs = env._get_obs()
            done = False
            step_idx = 0

            # Save initial screenshot
            if obs.get("screenshot"):
                with open(task_result_dir / "step_0_initial.png", "wb") as f:
                    f.write(obs["screenshot"])

            # Agent loop
            while not done and step_idx < args.max_steps:
                step_start = time.time()

                response, actions = agent.predict(instruction, obs)

                for action in actions:
                    action_ts = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")
                    logger.info(f"Step {step_idx + 1}: {action[:100]}")

                    obs, reward, done, info = env.step(
                        action, args.sleep_after_execution
                    )

                    logger.info(f"Reward: {reward}, Done: {done}")

                    # Save screenshot
                    if obs.get("screenshot"):
                        with open(
                            task_result_dir / f"step_{step_idx+1}_{action_ts}.png",
                            "wb"
                        ) as f:
                            f.write(obs["screenshot"])

                    # Save trajectory
                    with open(task_result_dir / "traj.jsonl", "a") as f:
                        f.write(json.dumps({
                            "step_num": step_idx + 1,
                            "action": action,
                            "response": response[:500],
                            "reward": reward,
                            "done": done,
                        }) + "\n")

                    if done:
                        break

                step_idx += 1

            # Wait for environment to settle
            logger.info("Waiting 20s for environment to settle...")
            time.sleep(20)

            # Evaluate
            score = env.evaluate()
            task_time = time.time() - task_start

            logger.info(f"Score: {score}")
            logger.info(f"Steps: {step_idx}")
            logger.info(f"Time: {task_time:.1f}s")

            scores.append(score)
            results.append({
                "task_id": task_id,
                "domain": domain,
                "instruction": instruction,
                "score": score,
                "steps": step_idx,
                "time_seconds": round(task_time, 1),
                "status": "completed" if done else "max_steps",
            })

            # Save individual result
            with open(task_result_dir / "result.txt", "w") as f:
                f.write(f"{score}\n")

        except Exception as e:
            task_time = time.time() - task_start
            logger.error(f"Error running task {task_id}: {e}", exc_info=True)
            scores.append(0.0)
            results.append({
                "task_id": task_id,
                "domain": domain,
                "score": 0.0,
                "steps": locals().get("step_idx", 0),
                "time_seconds": round(task_time, 1),
                "status": f"error: {str(e)[:100]}",
            })

        # Print running summary
        successes = sum(1 for s in scores if s > 0)
        logger.info(
            f"\nRunning: {successes}/{len(scores)} succeeded "
            f"({100*successes/len(scores):.1f}%)"
        )

    # Final summary
    total_time = time.time() - total_start
    successes = sum(1 for s in scores if s > 0)

    logger.info(f"\n{'='*60}")
    logger.info(f"FINAL RESULTS")
    logger.info(f"{'='*60}")
    logger.info(f"Tasks: {len(scores)}")
    logger.info(f"Successes: {successes}")
    logger.info(f"Success rate: {100*successes/max(len(scores),1):.1f}%")
    logger.info(f"Average score: {sum(scores)/max(len(scores),1):.3f}")
    logger.info(f"Total time: {total_time:.0f}s ({total_time/60:.1f}min)")

    # Per-domain breakdown
    domain_scores = {}
    for r in results:
        d = r.get("domain", "unknown")
        if d not in domain_scores:
            domain_scores[d] = []
        domain_scores[d].append(r.get("score", 0.0))

    logger.info("\nPer-domain breakdown:")
    for d, ds in sorted(domain_scores.items()):
        s = sum(1 for x in ds if x > 0)
        logger.info(f"  {d}: {s}/{len(ds)} ({100*s/len(ds):.0f}%)")

    # Save summary
    summary = {
        "timestamp": timestamp,
        "args": vars(args),
        "total_tasks": len(scores),
        "successes": successes,
        "success_rate": round(successes / max(len(scores), 1), 4),
        "average_score": round(sum(scores) / max(len(scores), 1), 4),
        "total_time_seconds": round(total_time, 1),
        "domain_breakdown": {
            d: {
                "total": len(ds),
                "successes": sum(1 for x in ds if x > 0),
                "rate": round(sum(1 for x in ds if x > 0) / len(ds), 4),
            }
            for d, ds in domain_scores.items()
        },
        "results": results,
    }

    with open(results_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    logger.info(f"\nResults saved to: {results_dir}")
    logger.info(f"Summary: {results_dir / 'summary.json'}")

    # Cleanup
    try:
        env.close()
    except Exception:
        pass

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run RPA agent on OSWorld benchmark")

    # Task selection
    parser.add_argument("--subset", default="small", choices=["small", "all"],
                        help="Task subset to run (default: small)")
    parser.add_argument("--domain", default=None,
                        help="Filter to specific domain (e.g., chrome, os, gimp)")
    parser.add_argument("--test_file", default=None,
                        help="Custom test file with task IDs")
    parser.add_argument("--task_ids", nargs="+", default=None,
                        help="Specific task IDs to run")
    parser.add_argument("--task_ids_file", default=None,
                        help="File with comma-separated task IDs to run")

    # Agent settings
    parser.add_argument("--vlm_url", default="http://localhost:23333/api/anthropic",
                        help="VLM endpoint URL")
    parser.add_argument("--vlm_api_key", default="custom",
                        help="VLM API key")
    parser.add_argument("--vlm_model", default="claude-opus-4.6-fast",
                        help="VLM model name")
    parser.add_argument("--max_tokens", type=int, default=4096)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--trajectory_length", type=int, default=10,
                        help="Max conversation history turns")
    parser.add_argument("--vlm_max_edge", type=int, default=1344,
                        help="Max image edge for VLM")
    parser.add_argument("--vlm_image_quality", type=int, default=50,
                        help="JPEG quality for VLM (1-100)")

    # Execution settings
    parser.add_argument("--max_steps", type=int, default=15,
                        help="Max steps per task")
    parser.add_argument("--env_wait", type=int, default=60,
                        help="Seconds to wait after env reset")
    parser.add_argument("--sleep_after_execution", type=float, default=3.0,
                        help="Sleep between action steps")
    parser.add_argument("--vm_password", default="password",
                        help="VM sudo password")
    parser.add_argument("--no_a11y", action="store_true",
                        help="Disable accessibility tree (much faster, ~10x speedup)")

    args = parser.parse_args()

    # Handle specific task IDs
    if args.task_ids_file:
        with open(args.task_ids_file) as f:
            args._specific_ids = [tid.strip() for tid in f.read().split(",") if tid.strip()]
    elif args.task_ids:
        # Override subset/domain with specific IDs
        args._specific_ids = args.task_ids
    else:
        args._specific_ids = None

    summary = run_benchmark(args)

    if summary:
        print(f"\nSuccess rate: {summary['success_rate']*100:.1f}%")
        print(f"Results: {summary.get('timestamp', 'unknown')}")


if __name__ == "__main__":
    main()
