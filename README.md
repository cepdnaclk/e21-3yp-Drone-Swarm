Drone swarms have emerged as an important research area in fields such as wireless communication, coordination, and collision avoidance. While many swarm algorithms are proposed and evaluated using simulation environments, real-world validation remains challenging due to unreliable wireless communication, sensor noise, and hardware variability.

This project presents an affordable and programmable indoor drone swarm testbed designed to support experimental swarm research under realistic conditions. The system enables researchers to deploy multiple small drones in a fixed indoor arena, upload swarm logic, and observe real wireless interactions between drones.

This work is developed as part of the PERA Swarm initiative, which aims to advance practical, accessible, and reusable platforms for swarm robotics and multi-agent system research.

By combining UWB-based localization, real drone-to-drone communication, and structured analytics such as packet loss and near-collision detection, the testbed aims to bridge the gap between simulation-based studies and real-world swarm experimentation.

## Automated Merge Checks

This repository now includes a GitHub Actions workflow at `.github/workflows/merge-checks.yml`.
It runs automatically on pull requests and on pushes to `main` or `master`.

Current checks:

- Python syntax validation for all `.py` files in the repository
- JSON validation for `docs/data/index.json`
- Basic structure validation for project metadata in `docs/data/index.json`

To make these checks block merges, enable branch protection in GitHub:

1. Open the repository on GitHub.
2. Go to `Settings` -> `Branches`.
3. Add a branch protection rule for your main branch.
4. Enable `Require status checks to pass before merging`.
5. Select the `Merge Checks` workflow job as a required check.

You can run the same checks locally with:

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```


```
{
  "title": "Progammable Drone Swarm",
  "team": [
    {
      "name": "Siyumi Herath",
      "email": "e21180@eng.pdn.ac.lk",
      "eNumber": "E/21/180"
    },
    {
      "name": "Ishan Kaushalya",
      "email": "e21217@eng.pdn.ac.lk",
      "eNumber": "E/21/217"
    },
    {
      "name": "Lisitha Abeysekara",
      "email": "e21009@eng.pdn.ac.lk",
      "eNumber": "E/21/009"
    },
    {
      "name": "Thinula ",
      "email": "e21156@eng.pdn.ac.lk",
      "eNumber": "E/21/156"
    }
  ],
  "supervisors": [
    {
      "name": "Dr. Supervisor 1",
      "email": "email@eng.pdn.ac.lk"
    },
    {
      "name": "Supervisor 2",
      "email": "email@eng.pdn.ac.lk"
    }
  ],
  "tags": ["Web", "Embedded Systems"]
}
```

Once you filled this _index.json_ file, please verify the syntax is correct. (You can use [this](https://jsonlint.com/) tool).

### Page Theme

A custom theme integrated with this GitHub Page, which is based on [github.com/cepdnaclk/eYY-project-theme](https://github.com/cepdnaclk/eYY-project-theme). If you like to remove this default theme, you can remove the file, _docs/\_config.yml_ and use HTML based website.
