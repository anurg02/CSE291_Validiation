import pandas as pd
import subprocess
import re
from pathlib import Path

# Load the first 10 code entries from the 'cross_stage_code' sheet
df = pd.read_excel("Flow-v2.xlsx", sheet_name="cross_stage_code").head(10)

results = []
Path("results").mkdir(exist_ok=True)

for idx, row in df.iterrows():
    raw_code = str(row[0])
    cleaned_code = re.sub(r"```python|```", "", raw_code).strip()

    script_path = Path(f"results/script_{idx+1}.py")
    script_path.write_text(cleaned_code)

    log_file_path = Path(f"results/log_{idx+1}.txt")

    try:
        result = subprocess.run(
            ["openroad", "-python", "-exit", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
            errors="replace"
        )

        # Save stdout + stderr to per-script log file
        log_file_path.write_text(result.stdout.strip())

        results.append({
            "index": idx + 1,
            "return_code": result.returncode,
            "log_file": log_file_path.name
        })

    except Exception as e:
        # Save exception message in a log file
        log_file_path.write_text(f"Exception: {str(e)}")
        results.append({
            "index": idx + 1,
            "return_code": -1,
            "log_file": log_file_path.name
        })

# Save results summary to Excel
output_df = pd.DataFrame(results)
output_df.to_excel("results/output_logs.xlsx", index=False)

print("✅ Executed first 10 scripts. Logs saved to 'results/log_*.txt' and summary to 'output_logs.xlsx'")

