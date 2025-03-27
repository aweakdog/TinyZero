"""Generate Countdown task data with different operator groups and train/test splits."""

import os
import random
from typing import List, Dict, Tuple
from datasets import Dataset
import sys
sys.path.append('.')
from examples.data_preprocess.countdown_generate import CountDown, dfs, bfs, sum_heuristic, mult_heuristic
from tqdm import tqdm
from rich import print as rprint


def make_prefix(dp, operators, template_type='base'):
    target = dp['target']
    numbers = dp['nums']
    # NOTE: also need to change reward_score/countdown.py
    if template_type == 'base':
        """This works for any base model"""
        prefix = f"""A conversation between User and Assistant. The user asks a question, and the Assistant solves it. The assistant first thinks about the reasoning process in the mind and then provides the user with the answer.
User: Using the numbers {numbers}, create an equation that equals {target}. You can use basic arithmetic operations ({', '.join(operators)}) and each number can only be used once. Show your work in <think> </think> tags. And return the final answer in <answer> </answer> tags, for example <answer> (1 + 2) / 3 </answer>.
Assistant: Let me solve this step by step.
<think>"""
    elif template_type == 'qwen-instruct':
        """This works for Qwen Instruct Models"""
        prefix = f"""<|im_start|>system\nYou are a helpful assistant. You first thinks about the reasoning process in the mind and then provides the user with the answer.<|im_end|>\n<|im_start|>user\n Using the numbers {numbers}, create an equation that equals {target}. You can use basic arithmetic operations ({', '.join(operators)}) and each number can only be used once. Show your work in <think> </think> tags. And return the final answer in <answer> </answer> tags, for example <answer> (1 + 2) / 3 </answer>.<|im_end|>\n<|im_start|>assistant\nLet me solve this step by step.\n<think>"""
    return prefix


class DataGenerator:
    def __init__(self, base_dir: str = "./data/continual"):
        self.base_dir = base_dir
        self.operator_groups = [
            ["+"],
            ["+", "-"],
            ["+", "-", "*"],
            ["+", "-", "*", "/"]
        ]
        self.group_names = [
            "plus",
            "plus_minus",
            "plus_minus_mul",
            "plus_minus_mul_div"
        ]
        os.makedirs(base_dir, exist_ok=True)

    def generate_group_data(self, group_idx: int, train_size: int = 7680, test_size: int = 7680) -> Tuple[Dataset, Dataset]:
        """Generate train and test data for a specific operator group"""
        operators = self.operator_groups[group_idx]
        group_name = self.group_names[group_idx]
        group_dir = os.path.join(self.base_dir, group_name)
        os.makedirs(group_dir, exist_ok=True)
        
        def generate_samples(num_samples: int, seed_offset: int = 0):
            random.seed(42 + group_idx + seed_offset)
            samples = []
            
            for _ in tqdm(range(num_samples), desc=f"Generating {num_samples} samples"):
                # Initialize countdown with random start size between 3 and 4
                start_size = random.randint(3, 4)
                cd = CountDown(max_target=1000, start_size=start_size, operators=operators)
                
                # Generate target and numbers
                ok = False
                while not ok:
                    target = random.randint(10, 1000)
                    nums, solution = cd.generate(target)
                    if solution is not None:
                        ok = True
                
                # Get optimal path
                no_backtrack_trace = cd.convert_to_path(target, nums, solution)
                
                # Random search strategy
                heuristic = random.choice([sum_heuristic, mult_heuristic])
                search = random.choice([dfs, bfs])
                
                if search == dfs:
                    search_path = dfs(target, nums, heuristic=heuristic, threshold=target)
                else:
                    beam_size = random.choice([1, 2, 3, 4, 5])
                    search_path = bfs(target, nums, beam_size, heuristic=heuristic)
                
                # Calculate rating
                max_rating = 3*4*4 if start_size == 3 else 1152  # Based on max nodes calculation
                if "Goal Reached" in search_path:
                    rating = 1.0
                else:
                    rating = 0.0
                
                samples.append({
                    "target": target,
                    "nums": nums,
                    "solution": solution,
                    "search_path": search_path,
                    "rating": rating,
                    "optimal_path": no_backtrack_trace,
                    "search_type": f"{search.__name__}{'_' + str(beam_size) if search == bfs else ''}",
                    "heuristic": heuristic.__name__
                })
            
            return samples
        
        rprint(f"[yellow]Generating training samples...[/yellow]")
        train_samples = generate_samples(train_size)
        
        rprint(f"[yellow]Generating test samples...[/yellow]")
        #test_samples = generate_samples(test_size, seed_offset=100)  # Different seed for test set
        test_samples = train_samples

        
        # Convert to dataset format
        def create_dataset(samples, split: str) -> Dataset:
            # Convert samples to proper dataset format
            data = {
                "target": [s["target"] for s in samples],
                "nums": [s["nums"] for s in samples],
                "solution": [s["solution"] for s in samples],
                "search_path": [s["search_path"] for s in samples],
                "rating": [s["rating"] for s in samples],
                "optimal_path": [s["optimal_path"] for s in samples],
                "search_type": [s["search_type"] for s in samples],
                "heuristic": [s["heuristic"] for s in samples]
            }
            dataset = Dataset.from_dict(data)
            
            def process_fn(example, idx):
                # Create prompt template
                question = make_prefix(example, operators=["+", "-", "*", "/"])

                # Add solution and metadata
                data = {
                    "data_source": "countdown_continual",
                    "prompt": [{
                        "role": "user",
                        "content": question,
                    }],
                    "ability": "math",
                    "reward_model": {
                        "style": "rule",
                        "ground_truth": {
                            "target": example['target'],
                            "numbers": example['nums'],
                            "solution": example['solution'],
                            "search_path": example['search_path'],
                            "rating": example['rating'],
                            "optimal_path": example['optimal_path']
                        }
                    },
                    "extra_info": {
                        'split': split,
                        'index': idx,
                        'operator_group': self.group_names[group_idx],
                        'search_type': example['search_type'],
                        'heuristic': example['heuristic']
                    }
                }
                return data
            
            # Map the processing function over the dataset
            dataset = dataset.map(function=process_fn, with_indices=True)
            
            # Save dataset
            output_path = os.path.join(group_dir, f"{split}.parquet")
            dataset.to_parquet(output_path)
            rprint(f"[green]Saved {split} dataset to {output_path}[/green]")
            
            return dataset
        
        train_dataset = create_dataset(train_samples, "train")
        test_dataset = create_dataset(test_samples, "test")
        
        return train_dataset, test_dataset

if __name__ == "__main__":
    rprint("[bold blue]Countdown Task Data Generator[/bold blue]")
    generator = DataGenerator()
    
    # Generate data for each operator group
    for group_idx in tqdm(range(len(generator.operator_groups)), desc="Generating datasets"):
        rprint(f"\n[bold cyan]Processing operator group: {generator.operator_groups[group_idx]}[/bold cyan]")
        train_dataset, test_dataset = generator.generate_group_data(group_idx)
        rprint(f"[green]✓ Generated {len(train_dataset)} training samples and {len(test_dataset)} test samples[/green]")
        rprint(f"[blue]  Saved in /data/countdown/continual/{generator.group_names[group_idx]}/[/blue]")
