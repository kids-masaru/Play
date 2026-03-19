import main_runner
import sys
import traceback

with open("my_err.txt", "w", encoding="utf-8") as f:
    sys.stdout = f
    sys.stderr = f
    try:
        main_runner.main()
    except Exception as e:
        f.write(traceback.format_exc())
