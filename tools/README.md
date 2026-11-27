# Manual diagnostic tools

From the repository root, with the configured development virtual environment:

```sh
python -m tools.probe --help
python -m tools.cloud_probe --help
python -m tools.smtp_probe --help
```

The legacy root scripts (`python probe.py`, `python cloud_probe.py`, `python smtp_probe.py`) forward to the same implementations, preserving their existing arguments, working-directory-relative paths and helper imports. Use module invocation from the repository root, not direct execution of the files inside tools/. Existing runtime modules are still at the root during phase 4a. These diagnostic tools are not required for production installation. No real credentials, images, databases or captures belong here.

The generated argparse usage line may show a different invocation name and wrap differently for module execution. The offline regression test in `tests.test_cli_help` compares normalized usage and the exact help body for all three tools; a raw text diff is not a valid compatibility criterion.

Reference-server verification: all three normalized comparisons passed at 9f9f8cf on 2026-11-27 (one test, 0.584 s).
