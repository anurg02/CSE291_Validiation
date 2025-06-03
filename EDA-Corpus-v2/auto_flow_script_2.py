import pandas as pd
import subprocess
import re
from pathlib import Path

# === Select which file to use ===
df = pd.read_csv("multi_agent_results_v2_updated_fixed.csv")
code_column = "final_script"  # or "final_script" for the other CSV

results = []
Path("results_2").mkdir(exist_ok=True)

for idx, row in df.iterrows():
    raw_code = str(row[code_column])
    cleaned_code = re.sub(r"```python|```", "", raw_code).strip()

    script_path = Path(f"results_2/script_{idx+1}.py")
    log_path = Path(f"results_2/log_{idx+1}.txt")
    script_path.write_text(cleaned_code)

    try:
        result = subprocess.run(
            ["openroad", "-python", "-exit", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
            errors="replace"
        )
        log_path.write_text(result.stdout.strip())
        results.append({
            "index": idx + 1,
            "return_code": result.returncode,
            "log_file": log_path.name
        })

    except Exception as e:
        log_path.write_text(f"Exception: {str(e)}")
        results.append({
            "index": idx + 1,
            "return_code": -1,
            "log_file": log_path.name
        })

# Save summary
output_df = pd.DataFrame(results)
output_df.to_excel("results_2/output_logs.xlsx", index=False)

print("✅ Execution complete. See results folder for logs and summary.")

