import pandas as pd
import re
from pathlib import Path

# === INPUT FILE SELECTION ===
input_files = [
    ("RAG_non-thinking-v2.csv", "response"),
    ("multi_agent_results_v2.csv", "final_script")
]

# === REPLACEMENT VALUES ===
design_dir_value = "../Design"
verilog_file_value = "1_synth.v"
design_name_value = "1_synth.v"
top_module_value = "gcd"

# === SCRIPT MODIFICATION FUNCTION ===
def replace_design_references(script: str) -> str:
    code = re.sub(r"```python|```", "", str(script)).strip()

    # Normalize and replace specific variable assignments
    code = re.sub(r"design_dir\s*=\s*.*", f'design_dir = "{design_dir_value}"', code)
    code = re.sub(r"designDir\s*=\s*Path\([^)]+\)", f'designDir = Path("{design_dir_value}")', code)

    code = re.sub(r"verilog_file\s*=\s*.*", f'verilog_file = "{verilog_file_value}"', code)
    code = re.sub(r"verilogFile\s*=\s*Path\([^)]+\)", f'verilogFile = Path("{verilog_file_value}")', code)

    code = re.sub(r"design_name\s*=\s*.*", f'design_name = "{design_name_value}"', code)
    code = re.sub(r"design_top_module_name\s*=\s*.*", f'design_top_module_name = "{top_module_value}"', code)

    return code

# === PROCESS AND SAVE ===
output_dir = Path("modified_scripts")
output_dir.mkdir(exist_ok=True)

for file_name, code_column in input_files:
    df = pd.read_csv(file_name)
    modified_column = f"{code_column}_modified"
    df[modified_column] = df[code_column].apply(replace_design_references)
    output_path = output_dir / file_name.replace(".csv", "_modified.csv")
    df.to_csv(output_path, index=False)
    print(f"✅ Saved modified file to: {output_path}")

