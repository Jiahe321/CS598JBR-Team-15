import os
import subprocess
import json
import jsonlines
import sys
import torch
import re
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
import ast


#####################################################
# Please finish all TODOs in this file for MP2;
#####################################################

def save_file(content, file_path):
    with open(file_path, 'w') as file:
        file.write(content)


def _drop_last_stmt(stmts):
    if not stmts:
        return
    last = stmts[-1]
    inner = getattr(last, "body", None)
    if isinstance(last, (ast.FunctionDef, ast.With, ast.For, ast.If)) and inner:
        _drop_last_stmt(inner)
        if not inner:
            stmts.pop()
    else:
        stmts.pop()


def split_asserts(code, truncated=False):
    lines = code.split("\n")
    tree = None
    while lines:
        try:
            tree = ast.parse("\n".join(lines))
            break
        except SyntaxError:
            lines.pop()
    if tree is None:
        return ""

    if truncated:
        _drop_last_stmt(tree.body)

    new_body = []
    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test")):
            if isinstance(node, ast.Assert):
                node = ast.FunctionDef(
                    name="test_module_level", args=ast.arguments(
                        posonlyargs=[], args=[], kwonlyargs=[],
                        kw_defaults=[], defaults=[]),
                    body=[node], decorator_list=[])
            else:
                new_body.append(node)
                continue

        setup, count, produced = [], 0, []
        for stmt in node.body:
            is_assert = isinstance(stmt, ast.Assert)
            is_compound_check = (
                                        not is_assert
                                        and isinstance(stmt, (ast.With, ast.For, ast.If))
                                        and any(isinstance(n, ast.Assert) for n in ast.walk(stmt))
                                ) or isinstance(stmt, ast.With)
            if is_assert or is_compound_check:
                count += 1
                produced.append(ast.FunctionDef(
                    name=f"{node.name}_{count}",
                    args=node.args,
                    body=list(setup) + [stmt],
                    decorator_list=node.decorator_list,
                ))
            else:
                setup.append(stmt)
        new_body.extend(produced if produced else [node])

    tree.body = new_body
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def prompt_model(dataset, model_name="deepseek-ai/deepseek-coder-6.7b-instruct", vanilla=True):
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
    current_dir = os.getcwd()
    if os.path.basename(current_dir) == "MP2":
        base_save_dir = current_dir
    else:
        base_save_dir = os.path.join(current_dir, "MP2")

    coverage_dir = os.path.join(base_save_dir, "Coverage")
    os.makedirs(base_save_dir, exist_ok=True)
    os.makedirs(coverage_dir, exist_ok=True)

    results = []
    for entry in dataset:
        task_id_safe = entry['task_id'].replace("/", "_")

        full_code = entry["prompt"] + "\n" + entry["canonical_solution"]

        # TODO: create prompt for the model
        # Tip : Use can use any data from the dataset to create
        #       the prompt including prompt, canonical_solution, test, etc.
        prompt = ""
        if vanilla:
            prompt = """You are an AI programming assistant. You are an AI programming assistant, utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.
### Instruction:
Generate a pytest test suite for the following code.
Only write unit tests in the output and nothing else.
{full_code}
### Response:"""
        else:
            prompt = """You are an AI programming assistant. You are an AI programming assistant, utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.

### Instruction:
Generate a comprehensive pytest test suite for the following code.
Please follow this requirement:
1. Pay special attention to all if-else statements, conditional branches, and boundary/edge cases to achieve full code coverage.
2. Outline a brief plan in comments for testing each branch and edge case before writing the tests. No more than 5 lines
3. Only write unit tests in the output and nothing else.
4. No need to repeat the given code in the output, only write the test suite.
5. Put your entire output (plan comments and unit tests) inside a single ```python ... ``` markdown code block.
### Code:
{full_code}

### Response:"""

        prompt = prompt.format(full_code=full_code)

        # TODO: prompt the model and get the response
        response = ""

        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_length=1000,
                do_sample=False,
                temperature=0,
                pad_token_id=tokenizer.eos_token_id
            )
        generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
        truncated = outputs.shape[1] >= 1000
        if "<|assistant|>" in generated_text:
            response = generated_text.split("<|assistant|>")[-1].strip()
        else:
            response = generated_text[len(prompt):].strip()

        code_blocks = re.findall(r'```(?:python)?(.*?)```', response, re.DOTALL)
        if code_blocks:
            selected_block = code_blocks[0]
            for block in code_blocks:
                if "test_" in block or "pytest" in block:
                    selected_block = block
                    break
            response = selected_block.strip()
        else:
            response = re.sub(r'^```(?:python)?', '', response.strip()).strip()
            response = response.split("```")[0].strip()
        response = response.replace("from your_module import", f"from {task_id_safe} import")
        response = response.replace("from module import", f"from {task_id_safe} import")
        response = response.replace("import your_module", f"import {task_id_safe}")

        def replacer(match):
            mod_name = match.group(1)
            if mod_name in ['typing', 'pytest', 'math', 'os', 'sys', 'collections', 'itertools']:
                return match.group(0)
            return f"from {task_id_safe} import"

        response = re.sub(r'from\s+([a-zA-Z_]\w*)\s+import', replacer, response)
        import_statement = f"from {task_id_safe} import *\n"
        response = split_asserts(response, truncated=truncated)
        lines = response.split('\n')
        filtered_lines = []
        skip = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('def ') and not stripped.startswith('def test_'):
                skip = True
            elif stripped.startswith('def test_'):
                skip = False

            if not skip:
                filtered_lines.append(line)

        response = '\n'.join(filtered_lines)

        if f"from {task_id_safe}" not in response and f"import {task_id_safe}" not in response:
            response = import_statement + response

        code_file_path = f"MP2/{task_id_safe}.py"
        save_file(full_code, code_file_path)

        test_file_path = f"MP2/{task_id_safe}_test.py"
        save_file(response, test_file_path)
        prompt_type_str = "vanilla" if vanilla else "crafted"
        coverage_json_path = f"MP2/Coverage/{task_id_safe}_test_{prompt_type_str}.json"

        cmd = [
            sys.executable, "-m", "pytest",
            test_file_path,
            f"--cov={task_id_safe}",
            f"--cov-report=json:{coverage_json_path}"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            pytest_output = result.stdout + "\n" + result.stderr

            passed_count = 0
            failed_count = 0
            total_tests = 0

            passed_match = re.search(r'(\d+)\s+passed', pytest_output)
            if passed_match:
                passed_count = int(passed_match.group(1))

            failed_match = re.search(r'(\d+)\s+failed', pytest_output)
            if failed_match:
                failed_count = int(failed_match.group(1))

            total_tests = passed_count + failed_count

            print(
                f"Task_ID {entry['task_id']}: total_tests: {total_tests}, pass_tests: {passed_count}, fail_tests: {failed_count}")

        except Exception as e:
            print(f"Error running pytest for {task_id_safe}: {e}")
            passed_count, failed_count, total_tests = 0, 0, 0
            pytest_output = str(e)

        # TODO: process the response, generate coverage and save it to results
        coverage = {}
        if os.path.exists(coverage_json_path):
            try:
                with open(coverage_json_path, 'r', encoding='utf-8') as f:
                    coverage = json.load(f)
            except Exception as e:
                print(f"Error reading coverage json for {task_id_safe}: {e}")

        print(f"Task_ID {entry['task_id']} processed successfully.")

        print(f"Task_ID {entry['task_id']}:\nprompt:\n{prompt}\nresponse:\n{response}\ncoverage:\n{coverage}")
        results.append({
            "task_id": entry["task_id"],
            "prompt": prompt,
            "response": response,
            "coverage": coverage,
            "total_tests": total_tests,
            "passed_tests": passed_count,
            "failed_tests": failed_count,
            "pytest_output": pytest_output
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
    This Python script is to run prompt LLMs for code synthesis.
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
    if_vanilla = args[3]  # True or False
    if not input_dataset.endswith(".jsonl"):
        raise ValueError(f"{input_dataset} should be a `.jsonl` file!")

    if not output_file.endswith(".jsonl"):
        raise ValueError(f"{output_file} should be a `.jsonl` file!")

    vanilla = True if if_vanilla == "True" else False

    dataset = read_jsonl(input_dataset)
    results = prompt_model(dataset, model, vanilla)
    write_jsonl(results, output_file)