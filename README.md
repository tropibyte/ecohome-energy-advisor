# EcoHome Energy Advisor (Udacity project)

**The submission is in [`ecohome_solution/`](ecohome_solution/)**. Start with its
[README](ecohome_solution/README.md), which maps every rubric item to where it is met.

| Folder | Contents |
|---|---|
| `ecohome_solution/` | The graded project: notebooks 01-03, agent, tools, RAG, data, reports, tests |
| `ecohome_starter/` | The untouched Udacity starter, kept for reference (not graded) |
| `dev/` | Scripts that generate the three notebooks' cells (`build_nb0*.py`); not needed to run the project |
| `requirements-starter-project.txt` | The dependency list that shipped with the starter bundle |

Quick start (Windows PowerShell, Python 3.11):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ecohome_solution\requirements.txt
.\.venv\Scripts\python.exe -m ipykernel install --user --name ecohome
copy ecohome_solution\.env.example ecohome_solution\.env   # add your Vocareum key
```

Then run `01_db_setup.ipynb`, `02_rag_setup.ipynb` and `03_run_and_evaluate.ipynb` in order with the `ecohome` kernel.
