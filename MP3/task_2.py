import jsonlines
import sys
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
import re

#####################################################
# Please finish all TODOs in this file for MP3/task_2;
#####################################################

def save_file(content, file_path):
    with open(file_path, 'w') as file:
        file.write(content)


def parse_prediction(response):
    predictions = re.findall(
        r"<start>\s*(buggy|correct)\s*<end>", response, re.IGNORECASE
    )
    if predictions:
        return predictions[-1].casefold(), "tags"

    # Like task_1, accept a prediction whose closing tag was omitted.
    match = re.search(
        r"<start>\s*(buggy|correct)\s*[.!]?\s*$", response, re.IGNORECASE
    )
    if match:
        return match.group(1).casefold(), "partial_tag"

    # Ignore code examples and repairs when looking for a prose conclusion.
    prose = re.sub(r"```.*?(?:```|$)", "", response, flags=re.DOTALL)
    conclusions = re.findall(
        r"\b(?:the\s+)?(?:final\s+)?(?:prediction|answer|verdict|conclusion)"
        r"\s*(?:is|should\s+be|:)\s*[\"'`*]*(buggy|correct)\b",
        prose, re.IGNORECASE
    )
    if conclusions:
        return conclusions[-1].casefold(), "text_conclusion"

    statements = re.findall(
        r"\b(?:the|this)\s+(?:(?:above|provided|given|original|current)\s+)?"
        r"(?:code|function|implementation|program)\s+is\s+"
        r"(not\s+)?(buggy|correct)\b", prose, re.IGNORECASE
    )
    labels = set()
    for negation, label in statements:
        label = label.casefold()
        if negation:
            label = "correct" if label == "buggy" else "buggy"
        labels.add(label)
    if len(labels) == 1:
        return labels.pop(), "text_statement"
    return "", "ambiguous" if labels else "missing"


def prompt_model(dataset, model_name = "deepseek-ai/deepseek-coder-6.7b-instruct", vanilla = True):
    print(f"Working with {model_name} prompt type {vanilla}...")
    
    # TODO: download the model
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    # TODO: load the model with quantization
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=True,
        device_map='auto',
        torch_dtype=torch.bfloat16,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type='nf4'
        ),
    )
    
    def generate(text, max_new_tokens):
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id
            )
        return tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

    results = []
    for entry in dataset:
        # TODO: create prompt for the model
        # Tip : Use can use any data from the dataset to create 
        #       the prompt including prompt, canonical_solution, test, etc.
        full_code = entry["declaration"] + "\n" + entry["buggy_solution"]
        if vanilla:
            prompt = """You are an AI programming assistant. You are an AI programming assistant utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.
### Instruction:

{full_code}
Is the above code buggy or correct? Please explain your step by step reasoning. The prediction should be enclosed within <start> and <end> tags. For example: <start>Buggy<end>
### Response:"""
        else:
            # Crafted prompt (two stages). Stage 1: the model writes its own implementation from the
            # docstring alone, which it does far better than judging code. Stage 2: it lists the
            # behavior-changing differences between that reference and the candidate code.
            spec = entry["prompt"]
            stage1 = """You are an AI programming assistant utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.
### Instruction:

Complete the following Python function so that it satisfies its docstring exactly. Output only the complete function in a single ```python code block, with no explanation.
{spec}
### Response:""".replace("{spec}", spec)
            reference = generate(stage1, 512)
            m = re.search(r"```(?:python)?\s*(.*?)(?:```|$)", reference, re.DOTALL)
            reference = (m.group(1) if m else reference).strip()
            full_code = entry["buggy_solution"].rstrip()
            prompt = """You are an AI programming assistant. You are an AI programming assistant utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.
### Instruction:

You are reviewing a Python function. First read its specification, then compare the candidate implementation with a reference implementation that was written independently from the same specification.

Specification:
{spec}

Reference implementation:
{reference}

Candidate implementation:

{full_code}

Follow these steps exactly:
Step 1 - Differences: compare the candidate with the reference part by part (conditions, operators, constants, indexes, variables, return values, edge-case handling) and list each difference as D1, D2, ... Ignore differences in naming, style or loop form that cannot change the result. Write "none" if there are no differences.
Step 2 - Impact: for each Di, pick a concrete input (use the specification examples when possible), write what the reference returns and what the candidate returns, and say CHANGES RESULT or SAME RESULT.
Step 3 - Decision: count the differences marked CHANGES RESULT. If the count is 1 or more, answer Buggy, even if the first specification example passes. If the count is 0, answer Correct.
Write the final prediction within <start> and <end> tags, for example <start>Buggy<end>, and stop writing after that tag.

Example 1:
Specification:
def count_even(numbers: List[int]) -> int:
    \"\"\" Return how many numbers in the list are even.
    >>> count_even([1, 2, 4])
    2
    \"\"\"
Reference implementation:
def count_even(numbers: List[int]) -> int:
    return sum(1 for n in numbers if n % 2 == 0)
Candidate implementation:
def count_even(numbers: List[int]) -> int:
    count = 0
    for n in numbers:
        if n % 2 == 1:
            count += 1
    return count
Step 1 - Differences: D1: the reference tests n % 2 == 0, the candidate tests n % 2 == 1.
Step 2 - Impact: D1: for [1, 2, 4] the reference returns 2 and the candidate returns 1. CHANGES RESULT.
Step 3 - Decision: 1 difference changes the result.
<start>Buggy<end>

Example 2:
Specification:
def clamp(x: int, low: int, high: int) -> int:
    \"\"\" Return x limited to the range from low to high.
    >>> clamp(5, 0, 10)
    5
    \"\"\"
Reference implementation:
def clamp(x: int, low: int, high: int) -> int:
    return max(low, min(x, high))
Candidate implementation:
def clamp(x: int, low: int, high: int) -> int:
    if x < low:
        return low
    if x > high:
        return low
    return x
Step 1 - Differences: D1: when x > high the reference returns high, the candidate returns low.
Step 2 - Impact: D1: for clamp(15, 0, 10) the reference returns 10 and the candidate returns 0. CHANGES RESULT. (For the docstring example clamp(5, 0, 10) both return 5, but that does not remove the difference.)
Step 3 - Decision: 1 difference changes the result.
<start>Buggy<end>

Now review this function.
### Response:"""
            prompt = (prompt.replace("{spec}", spec)
                      .replace("{reference}", reference).replace("{full_code}", entry["declaration"] + full_code))
            full_code = ""

        prompt = prompt.replace("{full_code}", full_code)
        # TODO: prompt the model and get the response
        response = generate(prompt, 1024)
        generated_tokens = tokenizer(response)["input_ids"]

        # TODO: process the response and save it to results
        model_result, prediction_source = parse_prediction(response)
        # Every input uses buggy_solution, so its ground-truth label is Buggy.
        # Only responses without a recoverable, unambiguous label are invalid.
        verdict = (model_result == "buggy")

        print(f"Task_ID {entry['task_id']}: prediction={model_result or 'unknown'}, "
              f"prediction_source={prediction_source}, generated_tokens={len(generated_tokens)}, "
              f"hit_token_limit={len(generated_tokens) >= 1024}")
        print(f"Task_ID {entry['task_id']}:\nprompt:\n{prompt}\nresponse:\n{response}\nis_expected:\n{verdict}")
        results.append({
            "task_id": entry["task_id"],
            "prompt": prompt,
            "response": response,
            "is_correct": verdict
        })
        
    return results

def read_jsonl(file_path):
    dataset = []
    with jsonlines.open(file_path) as reader:
        for line in reader: 
            dataset.append(line)
    return dataset

def write_jsonl(results, file_path):
    with jsonlines.open(file_path, "w") as f:
        for item in results:
            f.write_all([item])

if __name__ == "__main__":
    """
    This Python script is to run prompt LLMs for bug detection.
    Usage:
    `python3 task_2.py <input_dataset> <model> <output_file> <if_vanilla>`|& tee prompt.log

    Inputs:
    - <input_dataset>: A `.jsonl` file, which should be your team's dataset containing 20 HumanEval problems.
    - <model>: Specify the model to use. Options are "deepseek-ai/deepseek-coder-6.7b-base" or "deepseek-ai/deepseek-coder-6.7b-instruct".
    - <output_file>: A `.jsonl` file where the results will be saved.
    - <if_vanilla>: Set to 'True' or 'False' to enable vanilla prompt
    
    Outputs:
    - You can check <output_file> for detailed information.
    """
    args = sys.argv[1:]
    input_dataset = args[0]
    model = args[1]
    output_file = args[2]
    if_vanilla = args[3] # True or False
    
    if not input_dataset.endswith(".jsonl"):
        raise ValueError(f"{input_dataset} should be a `.jsonl` file!")
    
    if not output_file.endswith(".jsonl"):
        raise ValueError(f"{output_file} should be a `.jsonl` file!")
    
    vanilla = True if if_vanilla == "True" else False
    
    dataset = read_jsonl(input_dataset)
    results = prompt_model(dataset, model, vanilla)
    write_jsonl(results, output_file)
