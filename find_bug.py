import traceback
import main_runner
try:
    main_runner.main()
except Exception as e:
    with open('real_error.txt', 'w', encoding='utf-8') as f: f.write(traceback.format_exc())
